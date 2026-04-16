import app as _app
from app.models import ActivityLog
import logging

logger = logging.getLogger(__name__)


def _db():
    return _app.db_session


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
        _db().add(entry)
        _db().commit()
    except Exception as e:
        logger.error(f"Errore log activity: {e}")
        try:
            _db().rollback()
        except Exception:
            pass
