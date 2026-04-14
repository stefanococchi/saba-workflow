from flask import Blueprint, request, jsonify
from app import db_session as db
from app.models import Workflow, Participant, ParticipantStatus, WorkflowStatus
from app.services.activity_service import log_activity
from app.services import TokenService, SchedulerService
from app.services.sabaform_service import get_events, get_participants, get_event_by_id
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

participant_bp = Blueprint('participants', __name__)


@participant_bp.route('/workflows/<int:workflow_id>/participants', methods=['POST'])
def add_participants(workflow_id):
    """Aggiungi partecipanti a workflow"""
    try:
        workflow = db.get(Workflow, workflow_id)
        
        if not workflow:
            return jsonify({'error': 'Workflow non trovato'}), 404
        
        data = request.get_json()
        participants_data = data.get('participants', [])
        
        if not participants_data:
            return jsonify({'error': 'Lista partecipanti vuota'}), 400
        
        added = []
        
        for p_data in participants_data:
            # Verifica duplicati
            existing = db.query(Participant).filter_by(
                workflow_id=workflow_id,
                email=p_data['email']
            ).first()
            
            if existing:
                logger.warning(f"Partecipante {p_data['email']} già presente")
                continue
            
            # Crea partecipante
            participant = Participant(
                workflow_id=workflow_id,
                email=p_data['email'],
                name=p_data.get('name'),
                phone=p_data.get('phone')
            )
            
            db.add(participant)
            db.flush()
            
            # Genera token
            token = TokenService.generate_token(
                participant.id,
                workflow_id,
                expires_hours=workflow.token_expiration_hours
            )
            participant.token = token
            
            added.append({
                'id': participant.id,
                'email': participant.email,
                'name': participant.name
            })
        
        db.commit()
        
        logger.info(f"Aggiunti {len(added)} partecipanti a workflow {workflow_id}")
        
        return jsonify({
            'added': len(added),
            'participants': added
        }), 201
        
    except Exception as e:
        db.rollback()
        logger.error(f"Errore aggiunta partecipanti: {str(e)}")
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/workflows/<int:workflow_id>/participants', methods=['GET'])
def list_participants(workflow_id):
    """Lista partecipanti workflow"""
    try:
        workflow = db.get(Workflow, workflow_id)
        
        if not workflow:
            return jsonify({'error': 'Workflow non trovato'}), 404
        
        status_filter = request.args.get('status')
        
        query = db.query(Participant).filter_by(workflow_id=workflow_id)
        
        if status_filter:
            query = query.filter_by(status=ParticipantStatus(status_filter))
        
        participants = query.all()
        
        return jsonify({
            'participants': [
                {
                    'id': p.id,
                    'email': p.email,
                    'name': p.name,
                    'status': p.status.value,
                    'current_step_id': p.current_step_id,
                    'enrolled_at': p.enrolled_at.isoformat(),
                    'last_interaction': p.last_interaction.isoformat() if p.last_interaction else None,
                    'completed_at': p.completed_at.isoformat() if p.completed_at else None
                }
                for p in participants
            ]
        }), 200
        
    except Exception as e:
        logger.error(f"Errore lista partecipanti: {str(e)}")
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/workflows/<int:workflow_id>/start', methods=['POST'])
def start_workflow(workflow_id):
    """Start workflow for all pending participants"""
    try:
        workflow = db.get(Workflow, workflow_id)
        
        if not workflow:
            return jsonify({'error': 'Workflow not found'}), 404
        
        if not workflow.steps:
            return jsonify({'error': 'Workflow has no steps'}), 400
        
        # Get first step
        first_step = sorted(workflow.steps, key=lambda s: s.order)[0]
        
        # Get pending participants
        participants = db.query(Participant).filter_by(
            workflow_id=workflow_id,
            status=ParticipantStatus.PENDING
        ).all()
        
        if not participants:
            return jsonify({'error': 'No pending participants'}), 400
        
        scheduled_count = 0
        
        for participant in participants:
            # Schedule first step
            SchedulerService.schedule_step(
                participant,
                first_step,
                delay_hours=first_step.delay_hours
            )
            
            participant.status = ParticipantStatus.IN_PROGRESS
            participant.current_step_id = first_step.id
            scheduled_count += 1
        
        # Activate workflow
        workflow.status = WorkflowStatus.ACTIVE
        
        db.commit()
        
        logger.info(f"Started workflow {workflow_id} for {scheduled_count} participants")

        log_activity(
            workflow_id=workflow_id,
            event_type='workflow_started',
            description=f'Workflow avviato per {scheduled_count} partecipanti',
            details={'scheduled_count': scheduled_count, 'first_step': first_step.name}
        )

        return jsonify({
            'workflow_id': workflow_id,
            'scheduled': scheduled_count,
            'status': workflow.status.value
        }), 200
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error starting workflow: {str(e)}")
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/sabaform/events', methods=['GET'])
def list_sabaform_events():
    """Lista eventi da Saba Form (read-only)"""
    try:
        events = get_events()
        return jsonify({'events': events}), 200
    except Exception as e:
        logger.error(f"Errore lettura eventi sabaform: {e}")
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/sabaform/events/<int:event_id>/participants', methods=['GET'])
def list_sabaform_participants(event_id):
    """Lista partecipanti di un evento Saba Form (read-only, per preview/import)"""
    try:
        participants = get_participants(event_id)
        return jsonify({'participants': participants}), 200
    except Exception as e:
        logger.error(f"Errore lettura partecipanti sabaform: {e}")
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/workflows/<int:workflow_id>/import-participants', methods=['POST'])
def import_participants_from_sabaform(workflow_id):
    """Importa partecipanti da evento Saba Form nel workflow"""
    try:
        workflow = db.get(Workflow, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow non trovato'}), 404

        if not workflow.sabaform_event_id:
            return jsonify({'error': 'Nessun evento Saba Form collegato a questo workflow'}), 400

        # Leggi partecipanti da sabaform
        sf_participants = get_participants(workflow.sabaform_event_id)

        if not sf_participants:
            return jsonify({'error': 'Nessun partecipante trovato nell\'evento'}), 404

        imported = 0
        skipped = 0

        for p in sf_participants:
            name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            email = p.get('email', '').strip()

            # Deduplicazione: per email se presente, altrimenti per nome
            if email:
                existing = db.query(Participant).filter_by(
                    workflow_id=workflow_id,
                    email=email
                ).first()
            elif name:
                existing = db.query(Participant).filter_by(
                    workflow_id=workflow_id,
                    name=name
                ).first()
            else:
                existing = None

            if existing:
                skipped += 1
                continue

            participant = Participant(
                workflow_id=workflow_id,
                email=email or None,
                name=name or f"Partecipante {p.get('id', '')}",
                phone=p.get('phone', ''),
            )
            db.add(participant)
            db.flush()

            # Genera token
            token = TokenService.generate_token(
                participant.id, workflow_id,
                expires_hours=workflow.token_expiration_hours
            )
            participant.token = token

            imported += 1

        db.commit()

        logger.info(f"Import sabaform: {imported} importati, {skipped} duplicati per workflow {workflow_id}")

        return jsonify({
            'imported': imported,
            'skipped_duplicate': skipped,
            'total_in_event': len(sf_participants),
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Errore import partecipanti sabaform: {e}")
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/participants/<int:participant_id>/unsubscribe', methods=['POST'])
def unsubscribe_participant(participant_id):
    """Cancella partecipante (unsubscribe)"""
    try:
        participant = db.get(Participant, participant_id)
        
        if not participant:
            return jsonify({'error': 'Partecipante non trovato'}), 404
        
        # Cancella esecuzioni schedulate
        SchedulerService.cancel_scheduled_executions(participant_id)
        
        # Aggiorna stato
        participant.status = ParticipantStatus.UNSUBSCRIBED
        
        db.commit()
        
        logger.info(f"Unsubscribe partecipante {participant_id}")
        
        return jsonify({
            'participant_id': participant_id,
            'status': participant.status.value
        }), 200
        
    except Exception as e:
        db.rollback()
        logger.error(f"Errore unsubscribe: {str(e)}")
        return jsonify({'error': str(e)}), 500
