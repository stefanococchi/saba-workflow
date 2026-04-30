from datetime import datetime
import app as _app
from app.models import ActivityLog
import logging

logger = logging.getLogger(__name__)


def _db():
    return _app.db_session


OVERWRITABLE_EVENTS = {
    'landing_opened', 'opened', 'clicked', 'delivered',
}


def log_activity(workflow_id, event_type, description, participant_id=None, step_id=None, details=None):
    """Registra un'attività nel log. Per eventi ripetitivi sovrascrive il record precedente."""
    try:
        if event_type in OVERWRITABLE_EVENTS and participant_id and step_id:
            existing = _db().query(ActivityLog).filter_by(
                participant_id=participant_id,
                step_id=step_id,
                event_type=event_type,
            ).first()
            if existing:
                existing.description = description
                existing.details = details
                existing.created_at = datetime.utcnow()
                _db().commit()
                return

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
