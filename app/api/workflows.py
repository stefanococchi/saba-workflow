from flask import Blueprint, request, jsonify
from app import db_session as db
from app.models import Workflow, WorkflowStep, Participant, WorkflowStatus, Execution, ExecutionStatus
from app.services import TokenService, EmailService
from app.services.activity_service import log_activity
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
            name = p_data.get('name', '').strip()
            email = p_data.get('email', '').strip() or None
            if not name and not email:
                continue

            participant = Participant(
                workflow_id=workflow.id,
                email=email,
                name=name,
                phone=p_data.get('phone', ''),
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

        # Aggiorna steps se presenti (elimina vecchi, ricrea)
        if 'steps' in data:
            # Rimuovi step esistenti (cascade elimina anche executions)
            for old_step in list(workflow.steps):
                db.delete(old_step)
            db.flush()

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

        # Aggiungi nuovi partecipanti (non elimina quelli esistenti)
        participants_data = data.get('participants', [])
        for p_data in participants_data:
            name = p_data.get('name', '').strip()
            email = p_data.get('email', '').strip() or None
            if not name and not email:
                continue

            # Deduplicazione
            if email:
                existing = db.query(Participant).filter_by(workflow_id=workflow_id, email=email).first()
            elif name:
                existing = db.query(Participant).filter_by(workflow_id=workflow_id, name=name).first()
            else:
                existing = None

            if existing:
                continue

            participant = Participant(
                workflow_id=workflow.id,
                email=email,
                name=name,
                phone=p_data.get('phone', ''),
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
        
        db.delete(workflow)
        db.commit()
        
        logger.info(f"Eliminato workflow {workflow_id}")
        
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
                    'name': participant.name,
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
            description=f'Simulazione invio per {participant.name or participant.email}',
            participant_id=participant.id,
            details={'steps_count': len([s for s in steps_preview if not s.get('skipped')])}
        )

        return jsonify({
            'participant': {
                'id': participant.id,
                'name': participant.name,
                'email': participant.email,
            },
            'steps': steps_preview
        }), 200

    except Exception as e:
        logger.error(f"Errore simulazione workflow: {str(e)}")
        return jsonify({'error': str(e)}), 500
