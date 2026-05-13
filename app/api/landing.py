from flask import Blueprint, request, jsonify, render_template, render_template_string, current_app
from markupsafe import Markup
from app import db_session as db
from app.models import Participant, WorkflowStep, ParticipantStatus, StepType, ActivityLog, PaymentStatus
from app.services import TokenService, SchedulerService
from app.services.activity_service import log_activity
from app.services.payment_service import PaymentService, PaymentError
from datetime import datetime, timedelta
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

        # Priorità: step_id dal token (identifica quale email ha generato il link)
        current_step = None
        if payload.get('step_id'):
            current_step = db.get(WorkflowStep, payload['step_id'])

        # Fallback: primo step con landing page configurata
        if not current_step:
            current_step = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == participant.workflow_id,
                (WorkflowStep.landing_html.isnot(None)) | (WorkflowStep.landing_gjs_data.isnot(None))
            ).order_by(WorkflowStep.order).first()

        # Ultimo fallback: current_step del partecipante
        if not current_step:
            current_step = participant.current_step

        logger.info(f"Landing page: participant={participant.id}, step={current_step.id if current_step else None}, "
                     f"has_html={bool(current_step.landing_html) if current_step else False}")

        # Log landing page opened (deduplicate: max once per 30 min per participant)
        recent_open = db.query(ActivityLog).filter(
            ActivityLog.participant_id == participant.id,
            ActivityLog.event_type == 'landing_opened',
            ActivityLog.created_at >= datetime.utcnow() - timedelta(minutes=30)
        ).first()
        if not recent_open:
            log_activity(
                workflow_id=participant.workflow_id,
                event_type='landing_opened',
                description=f'{participant.full_name or participant.email} opened landing page',
                participant_id=participant.id,
                step_id=current_step.id if current_step else None,
            )

        landing_config = current_step.landing_page_config if current_step else {}

        # Payment configuration
        payment_config = {}
        if current_step:
            sc = current_step.skip_conditions or {}
            if sc.get('payment_enabled'):
                payment_config = {
                    'enabled': True,
                    'amount_cents': sc.get('payment_amount_cents', 0),
                    'currency': sc.get('payment_currency', current_app.config.get('STRIPE_PAYMENT_CURRENCY', 'eur')),
                    'description': sc.get('payment_description', ''),
                    'already_paid': PaymentService.has_successful_payment(participant.id, current_step.id),
                }

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
                                 token=token,
                                 payment_config=payment_config)

        # Altrimenti usa il form template di default
        return render_template('landing/form.html',
                             participant=participant,
                             workflow=participant.workflow,
                             config=landing_config,
                             token=token,
                             payment_config=payment_config)
        
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
        
        # Recupera partecipante (con lock per evitare race condition da double-click)
        participant = db.query(Participant).filter_by(
            id=payload['participant_id']
        ).with_for_update().first()

        if not participant:
            return jsonify({'error': 'Partecipante non trovato'}), 404

        # Verifica se già completato
        if participant.status == ParticipantStatus.COMPLETED:
            return jsonify({'error': 'Già completato'}), 400

        # Verifica se form già compilato (anti double-submit)
        # Ignore internal keys (_payment, _payment_pending, _payment_step_id) when checking
        if participant.collected_data:
            user_keys = [k for k in participant.collected_data.keys() if not k.startswith('_')]
            if user_keys:
                return jsonify({'success': True, 'message': 'Dati già salvati'}), 200

        # Guard: block direct submission if payment is required but not completed
        _guard_step = None
        if payload.get('step_id'):
            _guard_step = db.get(WorkflowStep, payload['step_id'])
        if _guard_step:
            _sc = _guard_step.skip_conditions or {}
            if _sc.get('payment_enabled'):
                _existing = dict(participant.collected_data or {})
                if not (_existing.get('_payment', {}).get('status') == 'completed'):
                    return jsonify({'error': 'Pagamento richiesto prima dell\'invio'}), 402

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

        db.commit()

        # Trova lo step landing corrente per avanzare al prossimo
        # Priorità: step_id dal token (identifica quale email ha generato il link)
        current_step = None
        if payload.get('step_id'):
            current_step = db.get(WorkflowStep, payload['step_id'])
        if not current_step:
            current_step = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == participant.workflow_id,
                (WorkflowStep.landing_html.isnot(None)) | (WorkflowStep.landing_gjs_data.isnot(None)) | (WorkflowStep.landing_page_config.isnot(None))
            ).order_by(WorkflowStep.order).first()
        if not current_step:
            current_step = participant.current_step

        # Log attività (con step_id)
        log_activity(
            workflow_id=participant.workflow_id,
            event_type='form_submitted',
            description=f'{participant.full_name or participant.email} ha compilato il form',
            participant_id=participant.id,
            step_id=current_step.id if current_step else None,
            details={'collected_data': existing}
        )

        if current_step:
            # If participant is already past the landing step (e.g. received a reminder),
            # bring them back to the landing step and apply its configured branch
            if participant.current_step_id and participant.current_step and \
               participant.current_step.order > current_step.order:
                SchedulerService.cancel_scheduled_executions(participant.id)
                participant.current_step_id = current_step.id
                db.commit()
                logger.info(f"Partecipante {participant.id} riportato a step {current_step.order} dopo form compilato")

            # Usa _handle_landing_branch per rispettare landing_if_filled/jump/stop
            config = current_step.skip_conditions or {}
            if_filled = config.get('landing_if_filled', 'continue')
            if_filled_step = config.get('landing_if_filled_step', 0)
            SchedulerService._handle_landing_branch(participant, current_step, if_filled, if_filled_step)
            logger.info(f"Partecipante {participant.id} completato landing, branch: {if_filled}")
        else:
            # Nessuno step trovato — marca completato come fallback
            participant.status = ParticipantStatus.COMPLETED
            participant.completed_at = datetime.utcnow()
            db.commit()
            logger.info(f"Partecipante {participant.id} completato workflow (nessuno step successivo)")

        return jsonify({
            'success': True,
            'message': 'Dati salvati con successo'
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Errore submit landing: {str(e)}")
        return jsonify({'error': str(e)}), 500


@landing_bp.route('/landing/<token>/checkout', methods=['POST'])
def create_checkout(token):
    """Create Stripe Checkout Session for landing page payment."""
    try:
        payload = TokenService.verify_token(token)
        if not payload:
            return jsonify({'error': 'Token non valido'}), 400

        participant = db.query(Participant).filter_by(
            id=payload['participant_id']
        ).with_for_update().first()

        if not participant:
            return jsonify({'error': 'Partecipante non trovato'}), 404

        if participant.status == ParticipantStatus.COMPLETED:
            return jsonify({'error': 'Già completato'}), 400

        # Find current step
        current_step = None
        if payload.get('step_id'):
            current_step = db.get(WorkflowStep, payload['step_id'])
        if not current_step:
            current_step = participant.current_step

        # Get payment config from skip_conditions
        config = current_step.skip_conditions or {} if current_step else {}
        if not config.get('payment_enabled'):
            return jsonify({'error': 'Pagamento non richiesto per questo step'}), 400

        amount_cents = int(config.get('payment_amount_cents', 0))
        if amount_cents <= 0:
            return jsonify({'error': 'Importo non configurato'}), 400

        currency = config.get('payment_currency', current_app.config.get('STRIPE_PAYMENT_CURRENCY', 'eur'))
        description = config.get('payment_description', f'{participant.workflow.name} - {current_step.name}')

        # Check for existing successful payment (idempotency)
        if PaymentService.has_successful_payment(participant.id, current_step.id):
            return jsonify({'error': 'Pagamento già effettuato'}), 400

        # Store form data temporarily with _payment_pending flag
        form_data = request.get_json() or {}
        existing = dict(participant.collected_data or {})
        existing.update(form_data)
        existing['_payment_pending'] = True
        existing['_payment_step_id'] = current_step.id
        participant.collected_data = existing
        db.commit()

        # Generate idempotency key
        idempotency_key = PaymentService.generate_idempotency_key(participant.id, current_step.id)

        # Build success/cancel URLs
        base_url = current_app.config['LANDING_BASE_URL'].rsplit('/landing', 1)[0]
        success_url = f"{base_url}/landing/{token}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_url}/landing/{token}/payment-cancelled"

        # Create Checkout Session
        result = PaymentService.create_checkout_session(
            participant_id=participant.id,
            workflow_id=participant.workflow_id,
            step_id=current_step.id,
            amount_cents=amount_cents,
            currency=currency,
            description=description,
            success_url=success_url,
            cancel_url=cancel_url,
            participant_email=participant.email,
            idempotency_key=idempotency_key,
        )

        # Log payment initiated
        log_activity(
            workflow_id=participant.workflow_id,
            event_type='payment_initiated',
            description=f'{participant.full_name or participant.email} initiated payment of {amount_cents / 100:.2f} {currency.upper()}',
            participant_id=participant.id,
            step_id=current_step.id,
            details={'amount_cents': amount_cents, 'currency': currency, 'stripe_session_id': result['session_id']}
        )

        return jsonify({'checkout_url': result['checkout_url']}), 200

    except PaymentError as e:
        db.rollback()
        logger.error(f"PAYMENT ERROR create_checkout: {str(e)}")
        return jsonify({'error': 'Errore creazione pagamento'}), 500
    except Exception as e:
        db.rollback()
        logger.error(f"PAYMENT ERROR create_checkout: {str(e)}", exc_info=True)
        return jsonify({'error': 'Errore creazione pagamento'}), 500


@landing_bp.route('/landing/<token>/payment-success', methods=['GET'])
def payment_success(token):
    """Stripe redirects here after successful payment. Verifies payment, saves data, triggers branching."""
    try:
        payload = TokenService.verify_token(token)
        if not payload:
            return render_template('landing/error.html', error='Link scaduto o non valido'), 400

        session_id = request.args.get('session_id')
        if not session_id:
            return render_template('landing/error.html', error='Sessione pagamento mancante'), 400

        participant = db.query(Participant).filter_by(
            id=payload['participant_id']
        ).with_for_update().first()

        if not participant:
            return render_template('landing/error.html', error='Partecipante non trovato'), 404

        # Verify payment with Stripe API
        session_data = PaymentService.verify_checkout_session(session_id)

        # Idempotency: if already processed, show success
        existing_data = dict(participant.collected_data or {})
        if existing_data.get('_payment', {}).get('status') == 'completed':
            return render_template('landing/payment_success.html',
                                 participant=participant, workflow=participant.workflow)

        # Mark payment as completed in collected_data
        step_id = existing_data.pop('_payment_step_id', payload.get('step_id'))
        existing_data.pop('_payment_pending', None)
        existing_data['_payment'] = {
            'status': 'completed',
            'amount_cents': session_data['amount_total'],
            'currency': session_data['currency'],
            'stripe_session_id': session_id,
            'stripe_payment_intent_id': session_data.get('payment_intent'),
            'paid_at': datetime.utcnow().isoformat(),
        }
        participant.collected_data = existing_data
        participant.last_interaction = datetime.utcnow()

        # Log to PaymentLog
        PaymentService.log_payment(
            participant_id=participant.id,
            workflow_id=participant.workflow_id,
            step_id=step_id,
            stripe_session_id=session_id,
            stripe_payment_intent_id=session_data.get('payment_intent'),
            amount_cents=session_data['amount_total'],
            currency=session_data['currency'],
            status=PaymentStatus.COMPLETED,
        )

        # Log to ActivityLog
        log_activity(
            workflow_id=participant.workflow_id,
            event_type='payment_completed',
            description=f'{participant.full_name or participant.email} paid {session_data["amount_total"] / 100:.2f} {session_data["currency"].upper()}',
            participant_id=participant.id,
            step_id=step_id,
            details={'stripe_session_id': session_id, 'amount_cents': session_data['amount_total']}
        )

        # Cancel follow-up scheduled executions
        SchedulerService.cancel_scheduled_executions(participant.id)

        db.commit()

        # Execute branching logic
        current_step = db.get(WorkflowStep, step_id) if step_id else None
        if current_step:
            config = current_step.skip_conditions or {}
            if_success = config.get('payment_if_success', config.get('landing_if_filled', 'continue'))
            if_success_step = config.get('payment_if_success_step', config.get('landing_if_filled_step', 0))
            SchedulerService._handle_landing_branch(participant, current_step, if_success, if_success_step)
        else:
            participant.status = ParticipantStatus.COMPLETED
            participant.completed_at = datetime.utcnow()
            db.commit()

        return render_template('landing/payment_success.html',
                             participant=participant, workflow=participant.workflow)

    except PaymentError as e:
        db.rollback()
        logger.error(f"PAYMENT ERROR payment_success: {str(e)}")
        return render_template('landing/error.html', error='Errore verifica pagamento. Se il pagamento è stato effettuato, verrà registrato automaticamente.'), 500
    except Exception as e:
        db.rollback()
        logger.error(f"PAYMENT ERROR payment_success: {str(e)}", exc_info=True)
        return render_template('landing/error.html', error='Errore verifica pagamento'), 500


@landing_bp.route('/landing/<token>/payment-cancelled', methods=['GET'])
def payment_cancelled(token):
    """Participant cancelled payment on Stripe page."""
    try:
        payload = TokenService.verify_token(token)
        if not payload:
            return render_template('landing/error.html', error='Link scaduto o non valido'), 400

        participant = db.get(Participant, payload['participant_id'])
        if not participant:
            return render_template('landing/error.html', error='Partecipante non trovato'), 404

        # Remove _payment_pending flag but keep form data
        existing = dict(participant.collected_data or {})
        existing.pop('_payment_pending', None)
        participant.collected_data = existing
        db.commit()

        log_activity(
            workflow_id=participant.workflow_id,
            event_type='payment_cancelled',
            description=f'{participant.full_name or participant.email} cancelled payment',
            participant_id=participant.id,
            step_id=payload.get('step_id'),
        )

        return render_template('landing/payment_cancelled.html',
                             participant=participant, workflow=participant.workflow, token=token)

    except Exception as e:
        logger.error(f"PAYMENT ERROR payment_cancelled: {str(e)}")
        return render_template('landing/error.html', error='Errore'), 500


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
