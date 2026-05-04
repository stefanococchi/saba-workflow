from flask import Blueprint, request, jsonify
from app import db_session as db
from app.models import Workflow, WorkflowStep, Participant, WorkflowStatus, Execution, ExecutionStatus, ActivityLog, ParticipantStatus
from app.services import TokenService, EmailService
from app.services.activity_service import log_activity
from app.services.scheduler_service import SchedulerService
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

workflow_bp = Blueprint('workflows', __name__)


@workflow_bp.route('/workflows', methods=['POST'])
def create_workflow():
    """Crea nuovo workflow"""
    try:
        data = request.get_json()
        
        # Validazione base
        if not data.get('name'):
            return jsonify({'error': 'Nome workflow richiesto'}), 400
        
        # Crea workflow
        workflow = Workflow(
            name=data['name'],
            description=data.get('description'),
            config=data.get('config', {}),
            created_by=data.get('created_by'),
            token_expiration_hours=data.get('token_expiration_hours'),
            sabaform_event_id=data.get('sabaform_event_id'),
            sabaform_event_name=data.get('sabaform_event_name'),
            mail_from_email=data.get('mail_from_email'),
            mail_from_name=data.get('mail_from_name'),
        )
        
        db.add(workflow)
        db.flush()  # Ottieni ID
        
        # Crea steps se presenti
        if 'steps' in data:
            for step_data in data['steps']:
                step = WorkflowStep(
                    workflow_id=workflow.id,
                    order=step_data.get('order', 1),
                    name=step_data.get('name', f"Step {step_data.get('order', 1)}"),
                    type=step_data.get('type', 'email'),
                    template_name=step_data.get('template_name'),
                    subject=step_data.get('subject', ''),
                    body_template=step_data.get('body_template', ''),
                    delay_hours=step_data.get('delay_hours', 0),
                    skip_conditions=step_data.get('skip_conditions'),
                    landing_page_config=step_data.get('landing_page_config')
                )
                db.add(step)

        # Crea partecipanti se presenti
        participants_data = data.get('participants', [])
        participants_added = 0
        for p_data in participants_data:
            first_name = p_data.get('first_name', '').strip()
            last_name = p_data.get('last_name', '').strip()
            email = p_data.get('email', '').strip() or None
            if not first_name and not last_name and not email:
                continue

            participant = Participant(
                workflow_id=workflow.id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=p_data.get('phone', ''),
                sabaform_data=p_data.get('sabaform_data', {}),
            )
            db.add(participant)
            db.flush()

            token = TokenService.generate_token(
                participant.id, workflow.id,
                expires_hours=workflow.token_expiration_hours
            )
            participant.token = token
            participants_added += 1

        db.commit()

        logger.info(f"Creato workflow {workflow.id}: {workflow.name} con {participants_added} partecipanti")
        from app.services.audit_service import log_user_action
        log_user_action('CREATE', 'Workflow', workflow.id, f'Created workflow "{workflow.name}" with {participants_added} participants')

        return jsonify({
            'id': workflow.id,
            'name': workflow.name,
            'status': workflow.status.value,
            'created_at': workflow.created_at.isoformat()
        }), 201
        
    except Exception as e:
        db.rollback()
        logger.error(f"Errore creazione workflow: {str(e)}")
        return jsonify({'error': str(e)}), 500


@workflow_bp.route('/workflows', methods=['GET'])
def list_workflows():
    """Lista tutti i workflows"""
    try:
        status_filter = request.args.get('status')
        
        query = db.query(Workflow)
        
        if status_filter:
            query = query.filter_by(status=WorkflowStatus(status_filter))
        
        workflows = query.order_by(Workflow.created_at.desc()).all()
        
        return jsonify({
            'workflows': [
                {
                    'id': w.id,
                    'name': w.name,
                    'description': w.description,
                    'status': w.status.value,
                    'steps_count': len(w.steps),
                    'participants_count': len(w.participants),
                    'created_at': w.created_at.isoformat()
                }
                for w in workflows
            ]
        }), 200
        
    except Exception as e:
        logger.error(f"Errore lista workflows: {str(e)}")
        return jsonify({'error': str(e)}), 500


@workflow_bp.route('/workflows/<int:workflow_id>', methods=['GET'])
def get_workflow(workflow_id):
    """Dettaglio workflow"""
    try:
        workflow = db.get(Workflow, workflow_id)
        
        if not workflow:
            return jsonify({'error': 'Workflow non trovato'}), 404
        
        return jsonify({
            'id': workflow.id,
            'name': workflow.name,
            'description': workflow.description,
            'status': workflow.status.value,
            'config': workflow.config,
            'created_at': workflow.created_at.isoformat(),
            'updated_at': workflow.updated_at.isoformat() if workflow.updated_at else None,
            'steps': [
                {
                    'id': s.id,
                    'order': s.order,
                    'name': s.name,
                    'type': s.type.value,
                    'subject': s.subject,
                    'delay_hours': s.delay_hours,
                    'has_landing_page': bool(s.landing_page_config)
                }
                for s in workflow.steps
            ],
            'participants_count': len(workflow.participants)
        }), 200
        
    except Exception as e:
        logger.error(f"Errore get workflow: {str(e)}")
        return jsonify({'error': str(e)}), 500


@workflow_bp.route('/workflows/<int:workflow_id>', methods=['PUT'])
def update_workflow(workflow_id):
    """Aggiorna workflow"""
    try:
        workflow = db.get(Workflow, workflow_id)
        
        if not workflow:
            return jsonify({'error': 'Workflow non trovato'}), 404
        
        data = request.get_json()
        
        # Aggiorna campi base
        if 'name' in data:
            workflow.name = data['name']
        if 'description' in data:
            workflow.description = data['description']
        if 'status' in data:
            workflow.status = WorkflowStatus(data['status'])
        if 'config' in data:
            workflow.config = data['config']
        if 'token_expiration_hours' in data:
            workflow.token_expiration_hours = data['token_expiration_hours']
        if 'sabaform_event_id' in data:
            workflow.sabaform_event_id = data['sabaform_event_id']
        if 'sabaform_event_name' in data:
            workflow.sabaform_event_name = data['sabaform_event_name']
        if 'mail_from_email' in data:
            workflow.mail_from_email = data['mail_from_email'] or None
        if 'mail_from_name' in data:
            workflow.mail_from_name = data['mail_from_name'] or None

        # Aggiorna steps se presenti (elimina vecchi, ricrea)
        if 'steps' in data:
            # PROTEZIONE: se il workflow è attivo, non ricreare gli step
            # (cancellazione step = cancellazione execution in cascade)
            has_active_executions = db.query(Execution).filter(
                Execution.step_id.in_([s.id for s in workflow.steps]),
                Execution.status.in_(['scheduled', 'sent'])
            ).first() is not None

            if has_active_executions:
                # Aggiorna step esistenti in-place senza eliminare
                old_steps_by_order = {s.order: s for s in workflow.steps}
                new_orders = {step_data.get('order', 1) for step_data in data['steps']}
                for step_data in data['steps']:
                    order = step_data.get('order', 1)
                    existing_step = old_steps_by_order.get(order)
                    if existing_step:
                        existing_step.name = step_data.get('name', existing_step.name)
                        existing_step.type = step_data.get('type', existing_step.type.value if hasattr(existing_step.type, 'value') else existing_step.type)
                        existing_step.subject = step_data.get('subject', existing_step.subject)
                        existing_step.body_template = step_data.get('body_template', existing_step.body_template)
                        existing_step.delay_hours = step_data.get('delay_hours', existing_step.delay_hours)
                        existing_step.skip_conditions = step_data.get('skip_conditions', existing_step.skip_conditions)
                        existing_step.landing_page_config = step_data.get('landing_page_config', existing_step.landing_page_config)
                    else:
                        step = WorkflowStep(
                            workflow_id=workflow.id,
                            order=order,
                            name=step_data.get('name', f"Step {order}"),
                            type=step_data.get('type', 'email'),
                            subject=step_data.get('subject', ''),
                            body_template=step_data.get('body_template', ''),
                            delay_hours=step_data.get('delay_hours', 0),
                            skip_conditions=step_data.get('skip_conditions'),
                            landing_page_config=step_data.get('landing_page_config')
                        )
                        db.add(step)

                # Elimina step rimossi dall'utente (solo se non hanno execution attive)
                for order, old_step in old_steps_by_order.items():
                    if order not in new_orders:
                        step_has_active = db.query(Execution).filter(
                            Execution.step_id == old_step.id,
                            Execution.status.in_(['scheduled', 'sent'])
                        ).first() is not None
                        if not step_has_active:
                            # Scollega partecipanti da questo step
                            db.query(Participant).filter(
                                Participant.current_step_id == old_step.id
                            ).update({Participant.current_step_id: None}, synchronize_session='fetch')
                            db.delete(old_step)
                        else:
                            logger.warning(f"Step {old_step.name} (order={order}) non eliminato: ha execution attive")
            else:
                # Nessuna execution attiva: ricrea normalmente
                # Salva dati landing page dai vecchi step (indicizzati per order)
                old_landing_data = {}
                for old_step in workflow.steps:
                    if old_step.landing_html or old_step.landing_css or old_step.landing_gjs_data:
                        old_landing_data[old_step.order] = {
                            'landing_html': old_step.landing_html,
                            'landing_css': old_step.landing_css,
                            'landing_gjs_data': old_step.landing_gjs_data,
                        }

                # Scollega partecipanti dai vecchi step
                old_step_ids = [s.id for s in workflow.steps]
                if old_step_ids:
                    db.query(Participant).filter(
                        Participant.current_step_id.in_(old_step_ids)
                    ).update({Participant.current_step_id: None}, synchronize_session='fetch')

                # Rimuovi step esistenti
                for old_step in list(workflow.steps):
                    db.delete(old_step)
                db.flush()

                for step_data in data['steps']:
                    order = step_data.get('order', 1)
                    step = WorkflowStep(
                        workflow_id=workflow.id,
                        order=order,
                        name=step_data.get('name', f"Step {order}"),
                        type=step_data.get('type', 'email'),
                        template_name=step_data.get('template_name'),
                        subject=step_data.get('subject', ''),
                        body_template=step_data.get('body_template', ''),
                        delay_hours=step_data.get('delay_hours', 0),
                        skip_conditions=step_data.get('skip_conditions'),
                        landing_page_config=step_data.get('landing_page_config')
                    )
                    # Ripristina landing page dallo step con lo stesso order
                    landing = old_landing_data.get(order)
                    if landing:
                        step.landing_html = landing['landing_html']
                        step.landing_css = landing['landing_css']
                        step.landing_gjs_data = landing['landing_gjs_data']

                    # Apply landing template if selected
                    skip = step_data.get('skip_conditions') or {}
                    tpl_id = skip.get('landing_template_id')
                    if tpl_id:
                        from app.models import LandingTemplate
                        tpl = db.get(LandingTemplate, tpl_id)
                        if tpl:
                            step.landing_html = tpl.landing_html
                            step.landing_css = tpl.landing_css
                            step.landing_gjs_data = tpl.landing_gjs_data

                    db.add(step)

        # Aggiungi nuovi partecipanti (non elimina quelli esistenti)
        participants_data = data.get('participants', [])
        for p_data in participants_data:
            first_name = p_data.get('first_name', '').strip()
            last_name = p_data.get('last_name', '').strip()
            email = p_data.get('email', '').strip() or None
            if not first_name and not last_name and not email:
                continue

            # Deduplicazione
            if email:
                existing = db.query(Participant).filter_by(workflow_id=workflow_id, email=email).first()
            elif first_name or last_name:
                existing = db.query(Participant).filter_by(
                    workflow_id=workflow_id, first_name=first_name, last_name=last_name
                ).first()
            else:
                existing = None

            if existing:
                # Aggiorna sabaform_data se presente
                sf_data = p_data.get('sabaform_data')
                if sf_data:
                    existing.sabaform_data = sf_data
                continue

            participant = Participant(
                workflow_id=workflow.id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=p_data.get('phone', ''),
                sabaform_data=p_data.get('sabaform_data', {}),
            )
            db.add(participant)
            db.flush()
            participant.token = TokenService.generate_token(
                participant.id, workflow.id,
                expires_hours=workflow.token_expiration_hours
            )

        workflow.updated_at = datetime.utcnow()

        db.commit()

        logger.info(f"Aggiornato workflow {workflow_id}")
        from app.services.audit_service import log_user_action
        log_user_action('UPDATE', 'Workflow', workflow.id, f'Updated workflow "{workflow.name}"')

        return jsonify({
            'id': workflow.id,
            'name': workflow.name,
            'status': workflow.status.value,
            'updated_at': workflow.updated_at.isoformat()
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Errore update workflow: {str(e)}")
        return jsonify({'error': str(e)}), 500


@workflow_bp.route('/workflows/<int:workflow_id>', methods=['DELETE'])
def delete_workflow(workflow_id):
    """Elimina workflow"""
    try:
        workflow = db.get(Workflow, workflow_id)
        
        if not workflow:
            return jsonify({'error': 'Workflow non trovato'}), 404
        
        # Verifica se può essere eliminato
        if workflow.status == WorkflowStatus.ACTIVE:
            return jsonify({'error': 'Non puoi eliminare workflow attivo'}), 400

        # Elimina activity_log collegati (non hanno cascade)
        db.query(ActivityLog).filter_by(workflow_id=workflow_id).delete()

        wf_name = workflow.name
        db.delete(workflow)
        db.commit()

        logger.info(f"Eliminato workflow {workflow_id}")
        from app.services.audit_service import log_user_action
        log_user_action('DELETE', 'Workflow', workflow_id, f'Deleted workflow "{wf_name}"')
        
        return jsonify({'message': 'Workflow eliminato'}), 200
        
    except Exception as e:
        db.rollback()
        logger.error(f"Errore delete workflow: {str(e)}")
        return jsonify({'error': str(e)}), 500


@workflow_bp.route('/workflows/<int:workflow_id>/simulate', methods=['POST'])
def simulate_workflow(workflow_id):
    """Simula l'invio email senza SMTP — renderizza template e genera landing URL"""
    try:
        workflow = db.get(Workflow, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow non trovato'}), 404

        data = request.get_json() or {}
        participant_id = data.get('participant_id')

        # Prendi il partecipante specificato o il primo disponibile
        if participant_id:
            participant = db.query(Participant).filter_by(
                id=participant_id, workflow_id=workflow_id
            ).first()
        else:
            participant = db.query(Participant).filter_by(
                workflow_id=workflow_id
            ).first()

        if not participant:
            return jsonify({'error': 'Nessun partecipante nel workflow. Aggiungine almeno uno.'}), 400

        # Simula ogni step email
        steps_preview = []
        for step in workflow.steps:
            if step.type.value != 'email':
                steps_preview.append({
                    'step_id': step.id,
                    'step_name': step.name,
                    'step_type': step.type.value,
                    'order': step.order,
                    'skipped': True,
                    'note': f'Step tipo "{step.type.value}" — non è un\'email'
                })
                continue

            # Genera landing URL — usa il token esistente del partecipante o ne genera uno nuovo
            from flask import current_app
            base_url = current_app.config.get('LANDING_BASE_URL', 'http://localhost:5001/landing')
            if participant.token:
                landing_url = f"{base_url}/{participant.token}"
            else:
                exp_hours = workflow.token_expiration_hours or current_app.config.get('JWT_EXPIRATION_HOURS', 72)
                sim_token = TokenService.generate_token(
                    participant.id, workflow.id, step_id=step.id,
                    expires_hours=exp_hours
                )
                participant.token = sim_token
                db.commit()
                landing_url = f"{base_url}/{sim_token}"

            # Contesto template
            context = {
                'participant': {
                    'name': participant.full_name,
                    'first_name': participant.first_name,
                    'last_name': participant.last_name,
                    'email': participant.email,
                },
                'landing_url': landing_url or '',
                'workflow_name': workflow.name,
                'evento': workflow.name,
                'step_name': step.name,
            }
            if workflow.config:
                context.update(workflow.config)

            # Renderizza
            try:
                rendered_subject = EmailService.render_template(step.subject or '', context)
                rendered_body = EmailService.render_template(step.body_template or '', context)
            except Exception as e:
                rendered_subject = f'[ERRORE TEMPLATE] {str(e)}'
                rendered_body = f'<p style="color:red">Errore rendering: {str(e)}</p>'

            steps_preview.append({
                'step_id': step.id,
                'step_name': step.name,
                'step_type': step.type.value,
                'order': step.order,
                'skipped': False,
                'subject': rendered_subject,
                'body_html': rendered_body,
                'landing_url': landing_url,
                'delay_hours': step.delay_hours,
            })

        log_activity(
            workflow_id=workflow_id,
            event_type='simulation',
            description=f'Simulazione invio per {participant.full_name or participant.email}',
            participant_id=participant.id,
            details={'steps_count': len([s for s in steps_preview if not s.get('skipped')])}
        )

        return jsonify({
            'participant': {
                'id': participant.id,
                'first_name': participant.first_name,
                'last_name': participant.last_name,
                'email': participant.email,
            },
            'steps': steps_preview
        }), 200

    except Exception as e:
        logger.error(f"Errore simulazione workflow: {str(e)}")
        return jsonify({'error': str(e)}), 500


@workflow_bp.route('/workflows/<int:workflow_id>/reconcile', methods=['GET'])
def reconcile_status(workflow_id):
    """Get participant breakdown for reconciliation."""
    try:
        result = SchedulerService.get_reconcile_status(workflow_id)
        if result is None:
            return jsonify({'error': 'Workflow non trovato'}), 404
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Errore reconcile status: {str(e)}")
        return jsonify({'error': str(e)}), 500


@workflow_bp.route('/workflows/<int:workflow_id>/reconcile', methods=['POST'])
def reconcile_execute(workflow_id):
    """Resume stuck participants with current workflow config."""
    try:
        workflow = db.get(Workflow, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow non trovato'}), 404

        data = request.get_json(silent=True) or {}
        participant_ids = data.get('participant_ids', [])

        # If no specific IDs, find all stuck participants
        if not participant_ids:
            status_data = SchedulerService.get_reconcile_status(workflow_id)
            for step_info in status_data.get('by_step', []):
                for sp in step_info.get('stuck', []):
                    participant_ids.append(sp['id'])

        results = []
        for pid in participant_ids:
            try:
                result = SchedulerService.reconcile_participant(pid)
                result['participant_id'] = pid
                results.append(result)

                if result['action'] not in ('skipped',):
                    p = db.get(Participant, pid)
                    log_activity(
                        workflow_id=workflow_id,
                        event_type='reconciled',
                        description=f'Partecipante riconciliato: {result["action"]}',
                        participant_id=pid,
                        step_id=p.current_step_id if p else None,
                        details=result
                    )
            except Exception as e:
                results.append({'participant_id': pid, 'action': 'error', 'reason': str(e)})

        reconciled = sum(1 for r in results if r['action'] not in ('skipped', 'error'))
        return jsonify({
            'reconciled': reconciled,
            'total': len(results),
            'results': results
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Errore reconcile: {str(e)}")
        return jsonify({'error': str(e)}), 500


@workflow_bp.route('/workflows/check-landing-waits', methods=['POST'])
def force_check_landing_waits():
    """Force immediate check of all landing wait participants."""
    try:
        SchedulerService.check_all_landing_waits()
        return jsonify({'ok': True}), 200
    except Exception as e:
        logger.error(f"Errore force check: {str(e)}")
        return jsonify({'error': str(e)}), 500
