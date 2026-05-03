"""User audit logging service"""
import threading
from datetime import datetime
from flask import session, request
from app.models import UserAuditLog
import logging

logger = logging.getLogger(__name__)


def _write_audit_log(app, data):
    """Write audit log entry in a background thread."""
    try:
        with app.app_context():
            from app import db_session as db
            entry = UserAuditLog(**data)
            db.add(entry)
            db.commit()
            db.remove()
    except Exception as e:
        logger.error(f"Audit log error: {e}")


def log_user_action(action, entity=None, entity_id=None, detail=''):
    """Log a user action to the audit trail.

    Actions: LOGIN, LOGOUT, LOGIN_FAIL, CREATE, UPDATE, DELETE
    Entities: Workflow, Participant, User, Settings
    """
    try:
        # Capture request context data now (before thread)
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
        if ',' in ip:
            ip = ip.split(',')[0].strip()

        data = dict(
            timestamp=datetime.utcnow(),
            user_id=session.get('user_id'),
            user_email=session.get('username', ''),
            action=action,
            entity=entity,
            entity_id=entity_id,
            detail=str(detail)[:500] if detail else '',
            ip_address=ip[:45] if ip else '',
        )

        from flask import current_app
        app = current_app._get_current_object()
        t = threading.Thread(target=_write_audit_log, args=(app, data), daemon=True)
        t.start()
    except Exception as e:
        logger.error(f"Audit log error: {e}")
