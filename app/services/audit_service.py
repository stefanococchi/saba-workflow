"""User audit logging service"""
from datetime import datetime
from flask import session, request
from app import db_session as db
from app.models import UserAuditLog
import logging

logger = logging.getLogger(__name__)


def log_user_action(action, entity=None, entity_id=None, detail=''):
    """Log a user action to the audit trail.

    Actions: LOGIN, LOGOUT, LOGIN_FAIL, CREATE, UPDATE, DELETE
    Entities: Workflow, Participant, User, Settings
    """
    try:
        # Get IP
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
        if ',' in ip:
            ip = ip.split(',')[0].strip()

        entry = UserAuditLog(
            timestamp=datetime.utcnow(),
            user_id=session.get('user_id'),
            user_email=session.get('username', ''),
            action=action,
            entity=entity,
            entity_id=entity_id,
            detail=str(detail)[:500] if detail else '',
            ip_address=ip[:45] if ip else '',
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        logger.error(f"Audit log error: {e}")
        try:
            db.rollback()
        except:
            pass
