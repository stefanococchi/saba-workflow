import urllib.parse
import requests as http_requests
from functools import wraps
from itsdangerous import URLSafeTimedSerializer
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, current_app, get_flashed_messages
from app import db_session as db
from app.models import User
import logging

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)


def _get_signer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])


def _sso_enabled():
    return bool(current_app.config.get('MS_SSO_CLIENT_ID'))


def get_current_user():
    """Get current logged-in user from session"""
    user_id = session.get('user_id')
    if user_id:
        return db.get(User, user_id)
    return None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth.login'))
        g.user = get_current_user()
        if not g.user:
            session.clear()
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def superuser_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth.login'))
        g.user = get_current_user()
        if not g.user or not g.user.is_superuser:
            flash('Access denied', 'danger')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated


# ── Microsoft SSO ─────────────────────────────────────────────────

@auth_bp.route('/auth/microsoft')
def microsoft_login():
    """Start OAuth2 flow with Microsoft Entra ID."""
    if not _sso_enabled():
        return redirect(url_for('auth.login', mode='local'))

    next_url = request.args.get('next', '')
    state = _get_signer().dumps({'next': next_url})

    params = {
        'client_id': current_app.config['MS_SSO_CLIENT_ID'],
        'response_type': 'code',
        'redirect_uri': current_app.config['MS_SSO_REDIRECT_URI'],
        'scope': 'openid profile email ' + ' '.join(current_app.config['MS_SSO_SCOPES']),
        'state': state,
        'response_mode': 'query',
    }
    auth_url = f"{current_app.config['MS_SSO_AUTHORITY']}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)


@auth_bp.route('/auth/callback')
def microsoft_callback():
    """OAuth2 callback from Microsoft."""
    # Verify signed state
    state = request.args.get('state', '')
    try:
        state_data = _get_signer().loads(state, max_age=600)
        next_url = state_data.get('next', '')
    except Exception:
        flash('Authentication session expired, please retry.', 'danger')
        return redirect(url_for('auth.login', mode='local'))

    code = request.args.get('code')
    if not code:
        error = request.args.get('error_description', request.args.get('error', 'Unknown error'))
        flash(f'Microsoft authentication error: {error}', 'danger')
        return redirect(url_for('auth.login', mode='local'))

    # Exchange code for tokens
    token_url = f"{current_app.config['MS_SSO_AUTHORITY']}/oauth2/v2.0/token"
    token_data = {
        'client_id': current_app.config['MS_SSO_CLIENT_ID'],
        'client_secret': current_app.config['MS_SSO_CLIENT_SECRET'],
        'code': code,
        'redirect_uri': current_app.config['MS_SSO_REDIRECT_URI'],
        'grant_type': 'authorization_code',
        'scope': 'openid profile email ' + ' '.join(current_app.config['MS_SSO_SCOPES']),
    }
    r = http_requests.post(token_url, data=token_data, timeout=15)
    if r.status_code != 200:
        flash('Error exchanging token with Microsoft.', 'danger')
        return redirect(url_for('auth.login', mode='local'))

    tokens = r.json()
    access_token = tokens.get('access_token')

    # Get user profile from Graph API
    headers = {'Authorization': f'Bearer {access_token}'}
    me = http_requests.get('https://graph.microsoft.com/v1.0/me', headers=headers, timeout=10).json()
    ms_id = me.get('id')
    ms_email = (me.get('mail') or me.get('userPrincipalName') or '').lower()

    if not ms_id or not ms_email:
        flash('Unable to retrieve user data from Microsoft.', 'danger')
        return redirect(url_for('auth.login', mode='local'))

    # Find user by microsoft_id or by email
    user = db.query(User).filter_by(microsoft_id=ms_id).first()
    if not user:
        user = db.query(User).filter_by(email=ms_email).first()
        if user:
            # Link existing account to Microsoft
            user.microsoft_id = ms_id
            db.commit()

    if not user:
        flash('Your Microsoft account is not authorized to access this system.', 'danger')
        return redirect(url_for('auth.login', mode='local'))

    # Save tokens
    user.ms_access_token = access_token
    if tokens.get('refresh_token'):
        user.ms_refresh_token = tokens['refresh_token']
    db.commit()

    # Login
    session['user_id'] = user.id
    session['username'] = user.username
    session['is_superuser'] = user.is_superuser
    logger.info(f"User {user.username} logged in via Microsoft SSO ({ms_email})")
    try:
        from app.services.audit_service import log_user_action
        log_user_action('LOGIN', 'Auth', user.id, f'SSO Microsoft: {ms_email}')
    except Exception:
        pass

    return redirect(next_url or url_for('admin.dashboard'))


# ── SSO Diagnostics (temporary – remove after debugging) ─────────

@auth_bp.route('/auth/sso-check')
def sso_check():
    """Diagnostic endpoint to verify SSO configuration."""
    from flask import jsonify
    import traceback

    try:
        cfg = current_app.config
        client_id = cfg.get('MS_SSO_CLIENT_ID', '')
        tenant_id = cfg.get('MS_SSO_TENANT_ID', '')
        authority = cfg.get('MS_SSO_AUTHORITY', '')
        redirect_uri = cfg.get('MS_SSO_REDIRECT_URI', '')
        has_secret = bool(cfg.get('MS_SSO_CLIENT_SECRET', ''))

        checks = {
            '1_sso_enabled': _sso_enabled(),
            '2_client_id': client_id[:8] + '...' if len(client_id) > 8 else ('MISSING' if not client_id else client_id),
            '3_tenant_id': tenant_id[:8] + '...' if len(tenant_id) > 8 else ('MISSING' if not tenant_id else tenant_id),
            '4_client_secret_set': has_secret,
            '5_authority': authority or 'MISSING',
            '6_redirect_uri': redirect_uri or 'MISSING',
            '7_scopes': cfg.get('MS_SSO_SCOPES', []),
        }

        # Test: can we reach the OpenID config endpoint?
        discovery_url = f"{authority}/v2.0/.well-known/openid-configuration"
        try:
            r = http_requests.get(discovery_url, timeout=10)
            checks['8_openid_discovery'] = {
                'url': discovery_url,
                'status': r.status_code,
                'ok': r.status_code == 200,
            }
            if r.status_code == 200:
                data = r.json()
                checks['8_openid_discovery']['issuer'] = data.get('issuer', '')
                checks['8_openid_discovery']['authorization_endpoint'] = data.get('authorization_endpoint', '')
        except Exception as e:
            checks['8_openid_discovery'] = {'error': str(e)}

        # Check: do any users in the DB have @sabae20.it emails?
        try:
            sabae_users = db.query(User).filter(User.email.ilike('%@sabae20.it')).all()
            checks['9_sabae20_users'] = [
                {'username': u.username, 'email': u.email, 'has_microsoft_id': bool(getattr(u, 'microsoft_id', None))}
                for u in sabae_users
            ]
        except Exception as e:
            checks['9_sabae20_users'] = {'error': str(e), 'hint': 'migration may not have run'}

        return jsonify(checks)

    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


# ── Local login ───────────────────────────────────────────────────

@auth_bp.route('/auth/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('admin.dashboard'))

    # Auto-redirect to SSO if configured (unless ?mode=local)
    if request.method == 'GET' and request.args.get('mode') != 'local':
        if _sso_enabled():
            get_flashed_messages()
            return redirect(url_for('auth.microsoft_login', next=request.args.get('next', '')))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = db.query(User).filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_superuser'] = user.is_superuser
            logger.info(f"User {username} logged in")
            try:
                from app.services.audit_service import log_user_action
                log_user_action('LOGIN', 'Auth', user.id, f'User {username} logged in')
            except Exception:
                pass
            return redirect(url_for('admin.dashboard'))

        flash('Invalid username or password', 'danger')
        try:
            from app.services.audit_service import log_user_action
            log_user_action('LOGIN_FAIL', 'Auth', detail=f'Failed login attempt for "{username}"')
        except Exception:
            pass

    return render_template('admin/login.html', sso_enabled=_sso_enabled())


@auth_bp.route('/auth/logout')
def logout():
    username = session.get('username', '?')
    from app.services.audit_service import log_user_action
    log_user_action('LOGOUT', 'Auth', detail=f'User {username} logged out')
    session.clear()
    logger.info(f"User {username} logged out")
    return redirect(url_for('auth.login', mode='local'))
