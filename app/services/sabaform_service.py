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
    """Ritorna lista partecipanti di un evento da sabaform con dati risolti.

    Risolve le foreign key (nucleus_id, flight_in_id, flight_out_id)
    con LEFT JOIN sulle tabelle correlate di Saba Form.

    Args:
        event_id: ID evento in sabaform

    Returns:
        list[dict]: tutti i campi del partecipante con valori risolti
    """
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            # Prima scopriamo quali tabelle/colonne correlate esistono
            # per costruire le JOIN in modo robusto
            fk_joins = ""
            fk_selects = ""

            # Verifica se esiste tabella nuclei/family_groups
            for table_name in ['nuclei', 'family_groups', 'nucleus']:
                try:
                    check = conn.execute(text(
                        f"SELECT column_name FROM information_schema.columns "
                        f"WHERE table_name = :t LIMIT 5"
                    ), {'t': table_name})
                    cols = [r[0] for r in check]
                    if cols:
                        name_col = 'name' if 'name' in cols else cols[1] if len(cols) > 1 else cols[0]
                        fk_joins += f" LEFT JOIN {table_name} n ON n.id = p.nucleus_id"
                        fk_selects += f", n.{name_col} AS nucleus_name"
                        break
                except Exception:
                    continue

            # Verifica se esiste tabella flights/voli
            for table_name in ['flights', 'voli', 'flight']:
                try:
                    check = conn.execute(text(
                        f"SELECT column_name FROM information_schema.columns "
                        f"WHERE table_name = :t LIMIT 10"
                    ), {'t': table_name})
                    cols = [r[0] for r in check]
                    if cols:
                        # Cerca colonna descrittiva: description, name, flight_number, code
                        desc_col = next((c for c in ['description', 'name', 'flight_number', 'code', 'label'] if c in cols), cols[1] if len(cols) > 1 else cols[0])
                        fk_joins += f" LEFT JOIN {table_name} fi ON fi.id = p.flight_in_id"
                        fk_joins += f" LEFT JOIN {table_name} fo ON fo.id = p.flight_out_id"
                        fk_selects += f", fi.{desc_col} AS flight_in_name"
                        fk_selects += f", fo.{desc_col} AS flight_out_name"
                        break
                except Exception:
                    continue

            query = f"""
                SELECT p.*{fk_selects}
                FROM participants p{fk_joins}
                WHERE p.event_id = :event_id
                ORDER BY p.last_name, p.first_name
            """
            logger.debug(f"Query sabaform participants: {query}")
            result = conn.execute(text(query), {'event_id': event_id})

            # Mappa per tradurre doc_type
            doc_type_labels = {
                'id_card': 'Carta d\'identità',
                'passport': 'Passaporto',
                'driving_license': 'Patente',
                'fiscal_code': 'Codice Fiscale',
                'health_card': 'Tessera Sanitaria',
            }

            # Campi da escludere (FK raw che abbiamo risolto)
            skip_keys = {'event_id', 'created_at', 'updated_at'}
            fk_resolved = set()
            if fk_selects:
                if 'nucleus_name' in fk_selects:
                    fk_resolved.add('nucleus_id')
                if 'flight_in_name' in fk_selects:
                    fk_resolved.add('flight_in_id')
                if 'flight_out_name' in fk_selects:
                    fk_resolved.add('flight_out_id')

            participants = []
            for row in result.mappings():
                p = {}
                for key, value in row.items():
                    if key in skip_keys or key in fk_resolved:
                        continue
                    if value is None:
                        continue
                    # Traduci doc_type
                    if key == 'doc_type' and isinstance(value, str):
                        p[key] = doc_type_labels.get(value, value)
                    elif hasattr(value, 'isoformat'):
                        p[key] = value.isoformat()
                    else:
                        p[key] = str(value) if not isinstance(value, (str, int, float, bool)) else value

                # Rinomina campi risolti con nomi leggibili
                if p.get('nucleus_name'):
                    p['nucleo'] = p.pop('nucleus_name')
                if p.get('flight_in_name'):
                    p['volo_arrivo'] = p.pop('flight_in_name')
                if p.get('flight_out_name'):
                    p['volo_partenza'] = p.pop('flight_out_name')

                participants.append(p)
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
