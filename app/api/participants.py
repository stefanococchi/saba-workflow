from flask import Blueprint, request, jsonify
from app import db_session as db
from app.models import Workflow, Participant, ParticipantStatus, WorkflowStatus, Execution, ActivityLog
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
                first_name=p_data.get('first_name', ''),
                last_name=p_data.get('last_name', ''),
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
                'first_name': participant.first_name,
                'last_name': participant.last_name
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
                    'first_name': p.first_name,
                    'last_name': p.last_name,
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
        updated = 0

        for p in sf_participants:
            first_name = p.get('first_name', '').strip() if p.get('first_name') else ''
            last_name = p.get('last_name', '').strip() if p.get('last_name') else ''
            email = str(p.get('email', '') or '').strip()

            # Tutti i dati originali da Saba Form
            sabaform_data = {k: v for k, v in p.items() if v is not None and v != ''}

            # Deduplicazione: per email se presente, altrimenti per nome
            existing = None
            if email:
                existing = db.query(Participant).filter_by(
                    workflow_id=workflow_id,
                    email=email
                ).first()
            elif first_name or last_name:
                existing = db.query(Participant).filter_by(
                    workflow_id=workflow_id,
                    first_name=first_name,
                    last_name=last_name
                ).first()

            if existing:
                # Aggiorna sabaform_data anche su partecipanti già importati
                existing.sabaform_data = sabaform_data
                if not existing.phone and p.get('phone'):
                    existing.phone = str(p['phone'])
                updated += 1
                continue

            participant = Participant(
                workflow_id=workflow_id,
                email=email or None,
                first_name=first_name or f"Partecipante",
                last_name=last_name or str(p.get('id', '')),
                phone=str(p.get('phone', '') or ''),
                sabaform_data=sabaform_data,
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

        logger.info(f"Import sabaform: {imported} nuovi, {updated} aggiornati per workflow {workflow_id}")

        return jsonify({
            'imported': imported,
            'updated': updated,
            'total_in_event': len(sf_participants),
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Errore import partecipanti sabaform: {e}")
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/participants/<int:participant_id>', methods=['GET'])
def get_participant(participant_id):
    """Dettaglio singolo partecipante"""
    try:
        p = db.get(Participant, participant_id)
        if not p:
            return jsonify({'error': 'Partecipante non trovato'}), 404
        return jsonify({
            'id': p.id,
            'workflow_id': p.workflow_id,
            'first_name': p.first_name,
            'last_name': p.last_name,
            'email': p.email,
            'phone': p.phone,
            'status': p.status.value,
            'current_step_id': p.current_step_id,
            'sabaform_data': p.sabaform_data or {},
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/participants/<int:participant_id>', methods=['PUT'])
def update_participant(participant_id):
    """Aggiorna dati partecipante"""
    try:
        participant = db.get(Participant, participant_id)
        if not participant:
            return jsonify({'error': 'Partecipante non trovato'}), 404

        data = request.get_json()

        if 'first_name' in data:
            participant.first_name = data['first_name']
        if 'last_name' in data:
            participant.last_name = data['last_name']
        if 'email' in data:
            participant.email = data['email'] or None
        if 'phone' in data:
            participant.phone = data['phone']
        if 'status' in data:
            participant.status = ParticipantStatus(data['status'])
        if 'sabaform_data' in data:
            participant.sabaform_data = data['sabaform_data']

        db.commit()
        logger.info(f"Aggiornato partecipante {participant_id}")

        return jsonify({
            'id': participant.id,
            'first_name': participant.first_name,
            'last_name': participant.last_name,
            'email': participant.email,
            'status': participant.status.value
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Errore update partecipante: {str(e)}")
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/participants/<int:participant_id>', methods=['DELETE'])
def delete_participant(participant_id):
    """Elimina partecipante"""
    try:
        participant = db.get(Participant, participant_id)
        if not participant:
            return jsonify({'error': 'Partecipante non trovato'}), 404

        db.delete(participant)
        db.commit()
        logger.info(f"Eliminato partecipante {participant_id}")

        return jsonify({'message': 'Partecipante eliminato'}), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Errore eliminazione partecipante: {str(e)}")
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/participants/<int:participant_id>/rollback', methods=['POST'])
def rollback_participant(participant_id):
    """Riporta un partecipante a uno step precedente (o a PENDING)"""
    try:
        participant = db.get(Participant, participant_id)
        if not participant:
            return jsonify({'error': 'Partecipante non trovato'}), 404

        data = request.get_json()
        target_step_order = data.get('step_order')  # None = reset a PENDING

        # Cancella esecuzioni schedulate
        SchedulerService.cancel_scheduled_executions(participant_id)

        if target_step_order is None or target_step_order == 0:
            # Reset completo a PENDING
            participant.status = ParticipantStatus.PENDING
            participant.current_step_id = None
            participant.last_interaction = None
            db.commit()

            log_activity(
                workflow_id=participant.workflow_id,
                event_type='status_changed',
                description=f'Partecipante riportato a PENDING',
                participant_id=participant_id,
                details={'action': 'rollback', 'target': 'pending'}
            )

            logger.info(f"Rollback partecipante {participant_id} a PENDING")
            return jsonify({'status': 'pending', 'message': 'Partecipante riportato a PENDING'}), 200
        else:
            # Riporta a uno step specifico
            from app.models import WorkflowStep
            target_step = db.query(WorkflowStep).filter_by(
                workflow_id=participant.workflow_id,
                order=target_step_order
            ).first()

            if not target_step:
                return jsonify({'error': f'Step {target_step_order} non trovato'}), 404

            # Elimina esecuzioni dallo step target in poi
            steps_to_clear = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == participant.workflow_id,
                WorkflowStep.order >= target_step_order
            ).all()
            step_ids = [s.id for s in steps_to_clear]

            if step_ids:
                db.query(Execution).filter(
                    Execution.participant_id == participant_id,
                    Execution.step_id.in_(step_ids)
                ).delete(synchronize_session='fetch')

            # Rigenera token (il vecchio potrebbe essere scaduto)
            participant.token = TokenService.generate_token(
                participant.id, participant.workflow_id,
                expires_hours=participant.workflow.token_expiration_hours
            )

            # Aggiorna partecipante
            participant.status = ParticipantStatus.IN_PROGRESS
            participant.current_step_id = target_step.id
            db.commit()

            # Schedula lo step target
            SchedulerService.schedule_step(participant, target_step, delay_hours=0)

            log_activity(
                workflow_id=participant.workflow_id,
                event_type='status_changed',
                description=f'Partecipante riportato a step {target_step.order}: {target_step.name}',
                participant_id=participant_id,
                step_id=target_step.id,
                details={'action': 'rollback', 'target_step': target_step.order, 'target_name': target_step.name}
            )

            logger.info(f"Rollback partecipante {participant_id} a step {target_step.order}: {target_step.name}")
            return jsonify({
                'status': 'in_progress',
                'step': target_step.name,
                'message': f'Partecipante riportato a: {target_step.name}'
            }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Errore rollback partecipante: {str(e)}")
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


@participant_bp.route('/activity-log/<int:entry_id>', methods=['DELETE'])
def delete_activity_log(entry_id):
    """Elimina entry dal log attività"""
    try:
        entry = db.get(ActivityLog, entry_id)
        if not entry:
            return jsonify({'error': 'Entry non trovata'}), 404
        db.delete(entry)
        db.commit()
        return jsonify({'message': 'Entry eliminata'}), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Errore eliminazione activity log: {str(e)}")
        return jsonify({'error': str(e)}), 500


@participant_bp.route('/executions/<int:execution_id>', methods=['DELETE'])
def delete_execution(execution_id):
    """Elimina esecuzione"""
    try:
        execution = db.get(Execution, execution_id)
        if not execution:
            return jsonify({'error': 'Esecuzione non trovata'}), 404
        db.delete(execution)
        db.commit()
        return jsonify({'message': 'Esecuzione eliminata'}), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Errore eliminazione esecuzione: {str(e)}")
        return jsonify({'error': str(e)}), 500
