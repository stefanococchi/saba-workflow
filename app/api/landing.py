from flask import Blueprint, request, jsonify, render_template, render_template_string
from markupsafe import Markup
from app import db_session as db
from app.models import Participant, WorkflowStep, ParticipantStatus
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
        
        # Verifica se già completato
        if participant.status == ParticipantStatus.COMPLETED:
            return render_template('landing/already_completed.html',
                                 participant=participant)
        
        # Ottieni step: da current_step del partecipante, o da step_id nel token, o primo step con landing
        current_step = participant.current_step
        if not current_step and payload.get('step_id'):
            current_step = db.get(WorkflowStep, payload['step_id'])
        if not current_step:
            # Fallback: primo step del workflow con landing configurata
            for s in participant.workflow.steps:
                if s.landing_html or s.landing_gjs_data or s.landing_page_config:
                    current_step = s
                    break

        landing_config = current_step.landing_page_config if current_step else {}

        # Se lo step ha un design custom (config template o GrapesJS), usa quello
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
