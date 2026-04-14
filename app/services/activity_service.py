from app import db_session as db
from app.models import ActivityLog
import logging

logger = logging.getLogger(__name__)


def log_activity(workflow_id, event_type, description, participant_id=None, step_id=None, details=None):
    """Registra un'attività nel log"""
    try:
        entry = ActivityLog(
            workflow_id=workflow_id,
            participant_id=participant_id,
            step_id=step_id,
            event_type=event_type,
            description=description,
            details=details,
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        logger.error(f"Errore log activity: {e}")
        try:
            db.rollback()
        except Exception:
            pass
