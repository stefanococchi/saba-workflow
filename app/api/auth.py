from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g
from app import db_session as db
from app.models import User
import logging

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)


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


@auth_bp.route('/auth/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = db.query(User).filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_superuser'] = user.is_superuser
            logger.info(f"User {username} logged in")
            from app.services.audit_service import log_user_action
            log_user_action('LOGIN', 'Auth', user.id, f'User {username} logged in')
            return redirect(url_for('admin.dashboard'))

        flash('Invalid username or password', 'danger')
        from app.services.audit_service import log_user_action
        log_user_action('LOGIN_FAIL', 'Auth', detail=f'Failed login attempt for "{username}"')

    return render_template('admin/login.html')


@auth_bp.route('/auth/logout')
def logout():
    username = session.get('username', '?')
    from app.services.audit_service import log_user_action
    log_user_action('LOGOUT', 'Auth', detail=f'User {username} logged out')
    session.clear()
    logger.info(f"User {username} logged out")
    return redirect(url_for('auth.login'))
