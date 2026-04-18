from flask import Blueprint, request, jsonify, render_template, render_template_string
from markupsafe import Markup
from app import db_session as db
from app.models import Participant, WorkflowStep, ParticipantStatus, StepType
from app.services import TokenService, SchedulerService
from app.services.activity_service import log_activity
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

landing_bp = Blueprint('landing', __name__)


@landing_bp.route('/landing/<token>', methods=['GET'])
def show_landing_page(token):
    """Mostra landing page per partecipante"""
    try:
        # Verifica token
        payload = TokenService.verify_token(token)
        
        if not payload:
            return render_template('landing/error.html', 
                                 error='Link scaduto o non valido'), 400
        
        # Recupera partecipante
        participant = db.get(Participant, payload['participant_id'])
        
        if not participant:
            return render_template('landing/error.html',
                                 error='Partecipante non trovato'), 404
        
        # Log landing page opened
        log_activity(
            workflow_id=participant.workflow_id,
            event_type='landing_opened',
            description=f'{participant.full_name or participant.email} opened landing page',
            participant_id=participant.id,
        )

        # Verifica se già completato
        if participant.status == ParticipantStatus.COMPLETED:
            return render_template('landing/already_completed.html',
                                 participant=participant)
        
        # Ottieni step con landing page configurata
        # Priorità: primo step con landing_html/gjs_data nel workflow
        current_step = None
        for s in sorted(participant.workflow.steps, key=lambda x: x.order):
            if s.landing_html or s.landing_gjs_data:
                current_step = s
                break

        # Fallback: step dal token o current_step del partecipante
        if not current_step and payload.get('step_id'):
            current_step = db.get(WorkflowStep, payload['step_id'])
        if not current_step:
            current_step = participant.current_step

        logger.info(f"Landing page: participant={participant.id}, step={current_step.id if current_step else None}, "
                     f"has_html={bool(current_step.landing_html) if current_step else False}")

        landing_config = current_step.landing_page_config if current_step else {}

        # Se lo step ha un design custom (HTML pre-generato), usa quello
        landing_html = None
        if current_step and current_step.landing_html:
            landing_html = current_step.landing_html
        elif current_step and current_step.landing_gjs_data and not current_step.landing_html:
            # Config template senza HTML pre-generato — usa form.html con config dal gjs_data
            gjs = current_step.landing_gjs_data
            if isinstance(gjs, dict) and gjs.get('fields'):
                landing_config = gjs

        if landing_html:
            return render_template('landing/custom.html',
                                 custom_html=landing_html,
                                 custom_css=current_step.landing_css or '',
                                 participant=participant,
                                 workflow=participant.workflow,
                                 token=token)

        # Altrimenti usa il form template di default
        return render_template('landing/form.html',
                             participant=participant,
                             workflow=participant.workflow,
                             config=landing_config,
                             token=token)
        
    except Exception as e:
        logger.error(f"Errore landing page: {str(e)}")
        return render_template('landing/error.html',
                             error='Errore caricamento pagina'), 500


@landing_bp.route('/landing/<token>', methods=['POST'])
def submit_landing_data(token):
    """Submit dati da landing page"""
    try:
        # Verifica token
        payload = TokenService.verify_token(token)
        
        if not payload:
            return jsonify({'error': 'Token non valido'}), 400
        
        # Recupera partecipante
        participant = db.get(Participant, payload['participant_id'])
        
        if not participant:
            return jsonify({'error': 'Partecipante non trovato'}), 404
        
        # Verifica se già completato
        if participant.status == ParticipantStatus.COMPLETED:
            return jsonify({'error': 'Già completato'}), 400
        
        # Salva dati
        form_data = request.get_json()

        # Validazione file upload (base64 in JSON)
        ALLOWED_MIME = {'application/pdf', 'image/jpeg', 'image/png',
                        'application/msword',
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        'application/vnd.ms-excel',
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
        MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

        for key, value in form_data.items():
            if isinstance(value, dict) and 'data' in value and 'filename' in value:
                # È un file upload
                if value.get('mime') not in ALLOWED_MIME:
                    return jsonify({'error': f'Tipo file non consentito: {value.get("mime")}'}), 400
                if value.get('size', 0) > MAX_FILE_SIZE:
                    return jsonify({'error': 'File troppo grande (max 20 MB)'}), 400

        # Merge con dati esistenti (riassegnazione per trigger change detection SQLAlchemy)
        existing = dict(participant.collected_data or {})
        existing.update(form_data)
        participant.collected_data = existing
        participant.last_interaction = datetime.utcnow()
        
        # Cancella follow-up schedulati (ha risposto)
        SchedulerService.cancel_scheduled_executions(participant.id)
        
        # Marca completato
        participant.status = ParticipantStatus.COMPLETED
        participant.completed_at = datetime.utcnow()
        
        db.commit()

        logger.info(f"Partecipante {participant.id} completato workflow")

        # Log attività
        log_activity(
            workflow_id=participant.workflow_id,
            event_type='form_submitted',
            description=f'{participant.full_name or participant.email} ha compilato il form',
            participant_id=participant.id,
            details={'collected_data': existing}
        )
        log_activity(
            workflow_id=participant.workflow_id,
            event_type='status_changed',
            description=f'{participant.full_name or participant.email} → completato',
            participant_id=participant.id,
            details={'old_status': 'in_progress', 'new_status': 'completed'}
        )

        return jsonify({
            'success': True,
            'message': 'Dati salvati con successo'
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Errore submit landing: {str(e)}")
        return jsonify({'error': str(e)}), 500


@landing_bp.route('/landing/<token>/unsubscribe', methods=['POST'])
def unsubscribe_from_landing(token):
    """Unsubscribe da landing page"""
    try:
        payload = TokenService.verify_token(token)
        
        if not payload:
            return jsonify({'error': 'Token non valido'}), 400
        
        participant = db.get(Participant, payload['participant_id'])
        
        if not participant:
            return jsonify({'error': 'Partecipante non trovato'}), 404
        
        # Cancella esecuzioni
        SchedulerService.cancel_scheduled_executions(participant.id)
        
        # Marca unsubscribed
        participant.status = ParticipantStatus.UNSUBSCRIBED

        db.commit()

        log_activity(
            workflow_id=participant.workflow_id,
            event_type='unsubscribed',
            description=f'{participant.full_name or participant.email} si è disiscritto',
            participant_id=participant.id,
        )

        return jsonify({
            'success': True,
            'message': 'Disiscrizione completata'
        }), 200
        
    except Exception as e:
        db.rollback()
        logger.error(f"Errore unsubscribe landing: {str(e)}")
        return jsonify({'error': str(e)}), 500


@landing_bp.route('/approval/<token>', methods=['GET'])
def handle_approval(token):
    """Handle approve/reject click from approver email"""
    try:
        payload = TokenService.verify_token(token)
        if not payload:
            return render_template('landing/error.html', error='Link expired or invalid'), 400

        participant = db.get(Participant, payload['participant_id'])
        if not participant:
            return render_template('landing/error.html', error='Participant not found'), 404

        action = request.args.get('action', '')
        if action not in ('approve', 'reject'):
            return render_template('landing/error.html', error='Invalid action'), 400

        # Check if approval was already handled (first-responder logic)
        existing = dict(participant.collected_data or {})
        if existing.get('_approval_handled'):
            previous_action = existing.get('_approval_action', 'unknown')
            return render_template('landing/approval_result.html',
                                 action=previous_action,
                                 already_handled=True,
                                 participant=participant,
                                 workflow=participant.workflow)

        # Find the human_approval step to read config
        approval_step = None
        for s in sorted(participant.workflow.steps, key=lambda x: x.order):
            if s.type == StepType.HUMAN_APPROVAL:
                approval_step = s
                break
        if not approval_step and payload.get('step_id'):
            approval_step = db.get(WorkflowStep, payload['step_id'])

        config = approval_step.skip_conditions or {} if approval_step else {}

        # Mark as handled immediately (first-responder wins)
        existing['_approval_handled'] = True
        existing['_approval_action'] = action
        existing['_approval_at'] = datetime.utcnow().isoformat()
        participant.collected_data = existing

        if action == 'approve':
            log_activity(
                workflow_id=participant.workflow_id,
                event_type='approval_granted',
                description=f'{participant.full_name or participant.email} approved',
                participant_id=participant.id,
            )
            # Execute configured action
            if_approved = config.get('if_approved', 'continue')
            if if_approved == 'complete':
                participant.status = ParticipantStatus.COMPLETED
                participant.completed_at = datetime.utcnow()
                SchedulerService.cancel_scheduled_executions(participant.id)
            elif if_approved == 'jump' and config.get('if_approved_step'):
                target_order = config['if_approved_step']
                target_step = next((s for s in participant.workflow.steps if s.order == target_order), None)
                if target_step:
                    SchedulerService.schedule_step(participant, target_step, delay_hours=0)
            else:
                # continue
                if approval_step:
                    SchedulerService._schedule_next_step(participant, approval_step)
        else:
            log_activity(
                workflow_id=participant.workflow_id,
                event_type='approval_rejected',
                description=f'{participant.full_name or participant.email} rejected',
                participant_id=participant.id,
            )
            if_rejected = config.get('if_rejected', 'stop')
            if if_rejected == 'continue':
                if approval_step:
                    SchedulerService._schedule_next_step(participant, approval_step)
            elif if_rejected == 'jump' and config.get('if_rejected_step'):
                target_order = config['if_rejected_step']
                target_step = next((s for s in participant.workflow.steps if s.order == target_order), None)
                if target_step:
                    SchedulerService.schedule_step(participant, target_step, delay_hours=0)
            else:
                # stop
                participant.status = ParticipantStatus.COMPLETED
                participant.completed_at = datetime.utcnow()
                SchedulerService.cancel_scheduled_executions(participant.id)

        db.commit()

        return render_template('landing/approval_result.html',
                             action=action,
                             already_handled=False,
                             participant=participant,
                             workflow=participant.workflow)

    except Exception as e:
        db.rollback()
        logger.error(f"Errore approval: {str(e)}")
        return render_template('landing/error.html', error='Error processing approval'), 500


@landing_bp.route('/survey/<token>', methods=['GET'])
def show_survey(token):
    """Click dall'email — salva la risposta immediatamente e mostra Grazie"""
    try:
        payload = TokenService.verify_token(token)
        if not payload:
            return render_template('landing/error.html', error='Link scaduto o non valido'), 400

        participant = db.get(Participant, payload['participant_id'])
        if not participant:
            return render_template('landing/error.html', error='Partecipante non trovato'), 404

        choice = request.args.get('choice', '')
        if not choice:
            return render_template('landing/error.html', error='Nessuna risposta selezionata'), 400

        # Trova lo step survey per il nome
        survey_step = None
        for s in sorted(participant.workflow.steps, key=lambda x: x.order):
            if s.type == StepType.SURVEY:
                survey_step = s
                break
        if not survey_step and payload.get('step_id'):
            survey_step = db.get(WorkflowStep, payload['step_id'])

        step_name = survey_step.name if survey_step else 'survey'
        config = survey_step.skip_conditions or {} if survey_step else {}
        question = config.get('question', '')

        # Salva risposta immediatamente
        existing = dict(participant.collected_data or {})
        existing[f'survey_{step_name}'] = choice
        participant.collected_data = existing
        participant.last_interaction = datetime.utcnow()

        db.commit()

        logger.info(f"Survey response from participant {participant.id}: {choice}")

        log_activity(
            workflow_id=participant.workflow_id,
            event_type='survey_submitted',
            description=f'{participant.full_name or participant.email} ha risposto al survey: {choice}',
            participant_id=participant.id,
            details={'step': step_name, 'choice': choice, 'question': question}
        )

        return render_template('landing/survey_thanks.html',
                             participant=participant,
                             workflow=participant.workflow,
                             question=question,
                             choice=choice)

    except Exception as e:
        db.rollback()
        logger.error(f"Errore survey: {str(e)}")
        return render_template('landing/error.html', error='Errore salvataggio risposta'), 500
