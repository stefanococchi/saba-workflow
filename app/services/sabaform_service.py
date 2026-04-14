"""
Servizio di connessione read-only al database Saba Form.
Legge eventi e partecipanti per import on-demand nei workflow.
"""
from sqlalchemy import create_engine, text
from flask import current_app
import logging

logger = logging.getLogger(__name__)

_engine = None


def _get_engine():
    """Crea/riusa engine di connessione al DB sabaform (lazy init)"""
    global _engine
    if _engine is None:
        uri = current_app.config.get('SABAFORM_DATABASE_URI')
        if not uri:
            raise RuntimeError('SABAFORM_DATABASE_URI non configurato')
        _engine = create_engine(uri, pool_pre_ping=True, pool_recycle=300)
    return _engine


def get_events():
    """Ritorna lista eventi da sabaform.

    Returns:
        list[dict]: [{id, name, client, start_date, end_date, estimated_participants, participant_count}]
    """
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    e.id,
                    e.name,
                    e.client,
                    e.date_from,
                    e.date_to,
                    e.estimated_participants,
                    COUNT(p.id) as participant_count
                FROM events e
                LEFT JOIN participants p ON p.event_id = e.id
                GROUP BY e.id, e.name, e.client, e.date_from, e.date_to, e.estimated_participants
                ORDER BY e.date_from DESC NULLS LAST, e.id DESC
            """))

            events = []
            for row in result.mappings():
                events.append({
                    'id': row['id'],
                    'name': row['name'],
                    'client': row['client'],
                    'start_date': str(row['date_from']) if row['date_from'] else None,
                    'end_date': str(row['date_to']) if row['date_to'] else None,
                    'estimated_participants': row['estimated_participants'],
                    'participant_count': row['participant_count'],
                })
            return events

    except Exception as e:
        logger.error(f"Errore lettura eventi sabaform: {e}")
        return []


def get_participants(event_id):
    """Ritorna lista partecipanti di un evento da sabaform.

    Args:
        event_id: ID evento in sabaform

    Returns:
        list[dict]: [{id, first_name, last_name, email, phone, company, birth_date, gender, notes}]
    """
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    p.id,
                    p.first_name,
                    p.last_name,
                    p.email,
                    p.phone,
                    p.company,
                    p.birth_date,
                    p.gender,
                    p.notes
                FROM participants p
                WHERE p.event_id = :event_id
                ORDER BY p.last_name, p.first_name
            """), {'event_id': event_id})

            participants = []
            for row in result.mappings():
                participants.append({
                    'id': row['id'],
                    'first_name': row['first_name'] or '',
                    'last_name': row['last_name'] or '',
                    'email': row['email'] or '',
                    'phone': row['phone'] or '',
                    'company': row['company'] or '',
                    'birth_date': str(row['birth_date']) if row['birth_date'] else None,
                    'gender': row['gender'],
                    'notes': row['notes'] or '',
                })
            return participants

    except Exception as e:
        logger.error(f"Errore lettura partecipanti sabaform evento {event_id}: {e}")
        return []


def get_event_by_id(event_id):
    """Ritorna un singolo evento da sabaform.

    Args:
        event_id: ID evento

    Returns:
        dict or None
    """
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, name, client, date_from, date_to, estimated_participants
                FROM events
                WHERE id = :event_id
            """), {'event_id': event_id})

            row = result.mappings().fetchone()
            if row:
                return {
                    'id': row['id'],
                    'name': row['name'],
                    'client': row['client'],
                    'start_date': str(row['date_from']) if row['date_from'] else None,
                    'end_date': str(row['date_to']) if row['date_to'] else None,
                    'estimated_participants': row['estimated_participants'],
                }
            return None

    except Exception as e:
        logger.error(f"Errore lettura evento sabaform {event_id}: {e}")
        return None
