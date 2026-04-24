from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, Response
from app import db_session as db
from app.models import Workflow, WorkflowStep, Participant, Execution, ActivityLog, WorkflowStatus, ParticipantStatus, ExecutionStatus, UploadedImage, Attachment, User, user_workflows
from app.api.auth import superuser_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload, subqueryload
from datetime import datetime
import logging
import uuid

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def get_visible_workflows(query=None):
    """Filter workflows based on current user permissions"""
    from flask import g
    if query is None:
        query = db.query(Workflow)
    user = getattr(g, 'user', None)
    if user and user.is_superuser:
        return query
    if user:
        wf_ids = [wf.id for wf in user.workflows]
        return query.filter(Workflow.id.in_(wf_ids)) if wf_ids else query.filter(Workflow.id == -1)
    return query.filter(Workflow.id == -1)


@admin_bp.route('/')
@admin_bp.route('/dashboard')
def dashboard():
    """Dashboard principale"""
    try:
        # Statistiche generali
        stats = {
            'total_workflows': db.query(Workflow).count(),
            'active_workflows': db.query(Workflow).filter_by(status=WorkflowStatus.ACTIVE).count(),
            'total_participants': db.query(Participant).count(),
            'emails_sent': db.query(Execution).filter_by(status=ExecutionStatus.SENT).count()
        }
        
        # Workflows per stato
        workflow_status_query = db.query(
            Workflow.status,
            func.count(Workflow.id)
        ).group_by(Workflow.status).all()
        
        workflow_status_labels = [status.value for status, _ in workflow_status_query]
        workflow_status_data = [count for _, count in workflow_status_query]
        
        # Partecipanti per stato
        participant_status_query = db.query(
            Participant.status,
            func.count(Participant.id)
        ).group_by(Participant.status).all()
        
        participant_status_labels = [status.value for status, _ in participant_status_query]
        participant_status_data = [count for _, count in participant_status_query]
        
        # Workflows recenti (filtered by user)
        recent_workflows = get_visible_workflows().options(
            selectinload(Workflow.steps),
            selectinload(Workflow.participants)
        ).order_by(
            Workflow.created_at.desc()
        ).limit(5).all()

        # Attività recenti (log unificato)
        recent_activities = db.query(ActivityLog).options(
            joinedload(ActivityLog.workflow),
            joinedload(ActivityLog.participant)
        ).order_by(
            ActivityLog.created_at.desc()
        ).limit(10).all()

        # Engagement — participants with last event (optimized: 3 queries instead of N*2)
        engagement_workflows = get_visible_workflows().options(
            selectinload(Workflow.participants)
        ).filter(Workflow.participants.any()).all()

        # Batch-fetch last activity and last execution per participant via subqueries
        participant_ids = [p.id for wf in engagement_workflows for p in wf.participants]

        last_activities = {}
        last_executions = {}
        if participant_ids:
            # Latest ActivityLog per participant
            latest_act_sub = db.query(
                ActivityLog.participant_id,
                func.max(ActivityLog.id).label('max_id')
            ).filter(
                ActivityLog.participant_id.in_(participant_ids)
            ).group_by(ActivityLog.participant_id).subquery()

            for a in db.query(ActivityLog).join(
                latest_act_sub, ActivityLog.id == latest_act_sub.c.max_id
            ).all():
                last_activities[a.participant_id] = a

            # Latest Execution per participant
            latest_exec_sub = db.query(
                Execution.participant_id,
                func.max(Execution.id).label('max_id')
            ).filter(
                Execution.participant_id.in_(participant_ids)
            ).group_by(Execution.participant_id).subquery()

            for ex in db.query(Execution).join(
                latest_exec_sub, Execution.id == latest_exec_sub.c.max_id
            ).all():
                last_executions[ex.participant_id] = ex

        engagement_participants = []
        for wf in engagement_workflows:
            for p in wf.participants:
                last_activity = last_activities.get(p.id)
                last_execution = last_executions.get(p.id)

                last_event = None
                last_event_time = None
                if last_activity and last_execution:
                    if (last_activity.created_at or datetime.min) > (last_execution.created_at or datetime.min):
                        last_event = last_activity.event_type
                        last_event_time = last_activity.created_at
                    else:
                        last_event = last_execution.status.value if last_execution.status else 'unknown'
                        last_event_time = last_execution.sent_at or last_execution.created_at
                elif last_activity:
                    last_event = last_activity.event_type
                    last_event_time = last_activity.created_at
                elif last_execution:
                    last_event = last_execution.status.value if last_execution.status else 'unknown'
                    last_event_time = last_execution.sent_at or last_execution.created_at

                engagement_participants.append({
                    'id': p.id,
                    'name': p.full_name or p.email,
                    'email': p.email,
                    'status': p.status.value,
                    'workflow_id': wf.id,
                    'workflow_name': wf.name,
                    'last_event': last_event,
                    'last_event_time': last_event_time,
                })

        return render_template('admin/dashboard.html',
                             stats=stats,
                             workflow_status_labels=workflow_status_labels,
                             workflow_status_data=workflow_status_data,
                             participant_status_labels=participant_status_labels,
                             participant_status_data=participant_status_data,
                             recent_workflows=recent_workflows,
                             recent_activities=recent_activities,
                             engagement_workflows=engagement_workflows,
                             engagement_participants=engagement_participants)

    except Exception as e:
        logger.error(f"Errore dashboard: {str(e)}")
        flash(f'Errore caricamento dashboard: {str(e)}', 'danger')
        return render_template('admin/dashboard.html',
                             stats={'total_workflows': 0, 'active_workflows': 0,
                                   'total_participants': 0, 'emails_sent': 0},
                             workflow_status_labels=[],
                             workflow_status_data=[],
                             participant_status_labels=[],
                             participant_status_data=[],
                             recent_workflows=[],
                             recent_activities=[],
                             engagement_workflows=[],
                             engagement_participants=[])


@admin_bp.route('/workflows')
def workflows_list():
    """Lista tutti i workflows"""
    try:
        # Filtri
        status_filter = request.args.get('status')
        
        query = get_visible_workflows()

        if status_filter:
            query = query.filter_by(status=WorkflowStatus(status_filter))

        workflows = query.order_by(Workflow.created_at.desc()).all()
        
        return render_template('admin/workflows_list.html',
                             workflows=workflows,
                             current_filter=status_filter)
    
    except Exception as e:
        logger.error(f"Errore lista workflows: {str(e)}")
        flash(f'Errore caricamento workflows: {str(e)}', 'danger')
        return render_template('admin/workflows_list.html',
                             workflows=[],
                             current_filter=None)


@admin_bp.route('/workflows/create')
def workflow_create():
    """Form creazione workflow"""
    return render_template('admin/workflow_form.html',
                         workflow=None,
                         mode='create')


@admin_bp.route('/workflows/<int:workflow_id>')
def workflow_detail(workflow_id):
    """Dettaglio workflow"""
    try:
        workflow = db.get(Workflow, workflow_id)
        
        if not workflow:
            flash('Workflow non trovato', 'danger')
            return redirect(url_for('admin.workflows_list'))
        
        return render_template('admin/workflow_detail.html',
                             workflow=workflow)
    
    except Exception as e:
        logger.error(f"Errore dettaglio workflow: {str(e)}")
        flash(f'Errore: {str(e)}', 'danger')
        return redirect(url_for('admin.workflows_list'))


@admin_bp.route('/workflows/<int:workflow_id>/edit')
def workflow_edit(workflow_id):
    """Form modifica workflow"""
    try:
        workflow = db.get(Workflow, workflow_id)
        
        if not workflow:
            flash('Workflow non trovato', 'danger')
            return redirect(url_for('admin.workflows_list'))
        
        return render_template('admin/workflow_form.html',
                             workflow=workflow,
                             mode='edit')
    
    except Exception as e:
        logger.error(f"Errore modifica workflow: {str(e)}")
        flash(f'Errore: {str(e)}', 'danger')
        return redirect(url_for('admin.workflows_list'))


@admin_bp.route('/participants')
def participants_list():
    """Lista partecipanti"""
    try:
        workflow_id = request.args.get('workflow_id', type=int)
        
        query = db.query(Participant).options(
            joinedload(Participant.workflow),
            joinedload(Participant.current_step)
        )

        if workflow_id:
            query = query.filter_by(workflow_id=workflow_id)

        participants = query.order_by(Participant.enrolled_at.desc()).all()
        
        workflows = db.query(Workflow).all()
        
        return render_template('admin/participants_list.html',
                             participants=participants,
                             workflows=workflows,
                             current_workflow_id=workflow_id)
    
    except Exception as e:
        logger.error(f"Errore lista partecipanti: {str(e)}")
        flash(f'Errore: {str(e)}', 'danger')
        return render_template('admin/participants_list.html',
                             participants=[],
                             workflows=[],
                             current_workflow_id=None)


@admin_bp.route('/workflows/<int:workflow_id>/steps/<int:step_id>/landing-builder')
def landing_builder(workflow_id, step_id):
    """Configuratore landing page"""
    try:
        step = db.query(WorkflowStep).filter_by(id=step_id, workflow_id=workflow_id).first()

        # Fallback: se lo step ID non esiste, cerca per ordine (gli ID cambiano dopo ogni save)
        if not step:
            step = db.query(WorkflowStep).filter_by(workflow_id=workflow_id, order=step_id).first()

        if not step:
            flash('Step non trovato', 'danger')
            return redirect(url_for('admin.workflow_detail', workflow_id=workflow_id))

        return render_template('admin/landing_config.html',
                             step=step,
                             config=step.landing_gjs_data)

    except Exception as e:
        logger.error(f"Errore landing config: {str(e)}")
        flash(f'Errore: {str(e)}', 'danger')
        return redirect(url_for('admin.workflow_detail', workflow_id=workflow_id))


@admin_bp.route('/collected-data')
def collected_data():
    """Vista dati raccolti da tutti i partecipanti"""
    try:
        workflow_id = request.args.get('workflow_id', type=int)

        query = db.query(Participant).options(
            joinedload(Participant.workflow)
        ).filter(
            Participant.collected_data.isnot(None)
        )
        if workflow_id:
            query = query.filter(Participant.workflow_id == workflow_id)

        participants = query.order_by(
            Participant.completed_at.is_(None).asc(),
            Participant.completed_at.desc()
        ).all()
        workflows = db.query(Workflow).all()

        # Raccogli tutti i field names unici
        all_fields = set()
        for p in participants:
            if p.collected_data and isinstance(p.collected_data, dict):
                all_fields.update(p.collected_data.keys())
        all_fields = sorted(all_fields)

        return render_template('admin/collected_data.html',
                             participants=participants,
                             workflows=workflows,
                             all_fields=all_fields,
                             current_workflow_id=workflow_id)

    except Exception as e:
        logger.error(f"Errore collected data: {str(e)}")
        flash(f'Errore: {str(e)}', 'danger')
        return render_template('admin/collected_data.html',
                             participants=[],
                             workflows=[],
                             all_fields=[],
                             current_workflow_id=None)


@admin_bp.route('/executions')
def executions_monitor():
    """Monitor esecuzioni"""
    try:
        workflow_id = request.args.get('workflow_id', type=int)
        
        query = db.query(Execution).join(Participant).options(
            joinedload(Execution.participant).joinedload(Participant.workflow),
            joinedload(Execution.step)
        )

        if workflow_id:
            query = query.filter(Participant.workflow_id == workflow_id)

        executions = query.order_by(Execution.scheduled_at.desc()).all()

        # Activity Log
        activity_query = db.query(ActivityLog).options(
            joinedload(ActivityLog.workflow),
            joinedload(ActivityLog.participant),
            joinedload(ActivityLog.step)
        )
        if workflow_id:
            activity_query = activity_query.filter(ActivityLog.workflow_id == workflow_id)
        activities = activity_query.order_by(ActivityLog.created_at.desc()).all()

        # Unifica in una timeline
        timeline = []
        for ex in executions:
            wf_name = ''
            if ex.participant and ex.participant.workflow:
                wf_name = ex.participant.workflow.name
            # Usa sent_at se disponibile, altrimenti scheduled_at
            display_time = ex.sent_at or ex.scheduled_at
            timeline.append({
                'type': 'execution',
                'entry_id': ex.id,
                'participant_id': ex.participant_id,
                'time': display_time,
                'event_type': 'email_failed' if ex.status.value == 'failed' else 'email_' + ex.status.value,
                'description': f'{ex.step.name}: {ex.status.value}' if ex.step else ex.status.value,
                'participant_name': (ex.participant.full_name or ex.participant.email or '—') if ex.participant else '—',
                'step_name': ex.step.name if ex.step else '—',
                'step_type': ex.step.type.value if ex.step else '',
                'workflow_name': wf_name,
                'error': ex.error_message,
                'details': ex.result_data,
            })
        for a in activities:
            wf_name = a.workflow.name if a.workflow else ''
            timeline.append({
                'type': 'activity',
                'entry_id': a.id,
                'participant_id': a.participant_id,
                'time': a.created_at,
                'event_type': a.event_type,
                'description': a.description,
                'participant_name': (a.participant.full_name or a.participant.email or '—') if a.participant else '—',
                'step_name': a.step.name if a.step else '—',
                'step_type': a.step.type.value if a.step else '',
                'workflow_name': wf_name,
                'error': None,
                'details': a.details,
            })

        timeline.sort(key=lambda x: x['time'], reverse=True)

        workflows = db.query(Workflow).all()

        return render_template('admin/executions_monitor.html',
                             timeline=timeline,
                             workflows=workflows,
                             current_workflow_id=workflow_id)

    except Exception as e:
        logger.error(f"Errore monitor esecuzioni: {str(e)}")
        flash(f'Errore: {str(e)}', 'danger')
        return render_template('admin/executions_monitor.html',
                             timeline=[],
                             workflows=[],
                             current_workflow_id=None)


@admin_bp.route('/activity-log')
@superuser_required
def activity_log():
    """User audit log — superuser only"""
    from app.translations import get_translations
    from app.models import UserAuditLog
    t = get_translations()
    try:
        action_filter = request.args.get('action', '')
        entity_filter = request.args.get('entity', '')
        user_filter = request.args.get('user', '').strip()
        days = request.args.get('days', 30, type=int)

        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = db.query(UserAuditLog).filter(UserAuditLog.timestamp >= cutoff)

        if action_filter:
            query = query.filter(UserAuditLog.action == action_filter)
        if entity_filter:
            query = query.filter(UserAuditLog.entity == entity_filter)
        if user_filter:
            query = query.filter(UserAuditLog.user_email.ilike(f'%{user_filter}%'))

        logs = query.order_by(UserAuditLog.timestamp.desc()).limit(500).all()

        all_actions = [r[0] for r in db.query(UserAuditLog.action).distinct().order_by(UserAuditLog.action).all()]
        all_entities = [r[0] for r in db.query(UserAuditLog.entity).distinct().order_by(UserAuditLog.entity).all() if r[0]]

        return render_template('admin/activity_log.html',
                             logs=logs,
                             all_actions=all_actions,
                             all_entities=all_entities,
                             action_filter=action_filter,
                             entity_filter=entity_filter,
                             user_filter=user_filter,
                             days_filter=days,
                             t=t)
    except Exception as e:
        logger.error(f"Errore activity log: {str(e)}")
        flash(f'Errore: {str(e)}', 'danger')
        return render_template('admin/activity_log.html',
                             logs=[], all_actions=[], all_entities=[],
                             action_filter='', entity_filter='',
                             user_filter='', days_filter=30, t=t)


ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}

MIME_TYPES = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'svg': 'image/svg+xml',
}


@admin_bp.route('/upload-image', methods=['POST'])
def upload_image():
    """Upload immagine per landing page (logo o sfondo) — salva in DB"""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file selezionato'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nessun file selezionato'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({'error': f'Formato non consentito. Usa: {", ".join(ALLOWED_IMAGE_EXTENSIONS)}'}), 400

    filename = f"{uuid.uuid4().hex}.{ext}"
    image = UploadedImage(
        filename=filename,
        mime_type=MIME_TYPES.get(ext, 'application/octet-stream'),
        data=file.read()
    )
    db.add(image)
    db.commit()

    url = url_for('admin.serve_image', image_id=image.id, _external=False)
    return jsonify({'url': url}), 200


@admin_bp.route('/images/<int:image_id>')
def serve_image(image_id):
    """Serve immagine dal DB"""
    image = db.query(UploadedImage).get(image_id)
    if not image:
        return 'Not found', 404
    return Response(
        image.data,
        mimetype=image.mime_type,
        headers={'Cache-Control': 'public, max-age=31536000'}
    )


ALLOWED_ATTACHMENT_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt', 'png', 'jpg', 'jpeg', 'gif', 'zip'}
MAX_ATTACHMENT_SIZE = int(3.9 * 1024 * 1024)  # 3.9 MB (Graph API limit)


@admin_bp.route('/api/attachments', methods=['POST'])
def upload_attachment():
    """Upload allegato per step email"""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file selezionato'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nessun file selezionato'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        return jsonify({'error': f'Formato non consentito. Usa: {", ".join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))}'}), 400

    data = file.read()
    if len(data) > MAX_ATTACHMENT_SIZE:
        return jsonify({'error': 'File troppo grande (max 10 MB)'}), 400

    attachment = Attachment(
        filename=file.filename,
        mime_type=file.content_type or 'application/octet-stream',
        size=len(data),
        data=data
    )
    db.add(attachment)
    db.commit()

    return jsonify({
        'id': attachment.id,
        'filename': attachment.filename,
        'size': attachment.size,
        'mime_type': attachment.mime_type
    }), 201


@admin_bp.route('/api/attachments/<int:attachment_id>', methods=['DELETE'])
def delete_attachment(attachment_id):
    """Elimina allegato"""
    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        return jsonify({'error': 'Not found'}), 404

    db.delete(attachment)
    db.commit()
    return jsonify({'success': True}), 200


@admin_bp.route('/api/attachments/info', methods=['POST'])
def get_attachments_info():
    """Restituisce metadati degli allegati dato un array di IDs"""
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify([]), 200

    attachments = db.query(Attachment).filter(Attachment.id.in_(ids)).all()
    return jsonify([{
        'id': a.id,
        'filename': a.filename,
        'size': a.size,
        'mime_type': a.mime_type
    } for a in attachments]), 200


@admin_bp.route('/api/participant/<int:participant_id>/timeline')
def participant_timeline(participant_id):
    """Timeline eventi per un partecipante"""
    try:
        participant = db.get(Participant, participant_id)
        if not participant:
            return jsonify({'error': 'Not found'}), 404

        USER_EVENTS = {'form_submitted', 'survey_submitted', 'unsubscribed', 'landing_opened', 'approval_granted', 'approval_rejected'}

        events = []

        # Execution records
        executions = db.query(Execution).options(
            joinedload(Execution.step)
        ).filter_by(participant_id=participant_id).all()
        for ex in executions:
            step_name = ex.step.name if ex.step else '?'
            step_type = ex.step.type.value if ex.step else '?'
            ts = ex.sent_at or ex.scheduled_at or ex.created_at

            icon = 'envelope'
            if step_type == 'survey':
                icon = 'ui-checks'
            elif step_type == 'goal_check':
                icon = 'trophy'
            elif step_type == 'condition':
                icon = 'shuffle'
            elif step_type == 'wait_until':
                icon = 'calendar-check'

            status_colors = {
                'SCHEDULED': '#6c757d', 'SENT': '#198754', 'FAILED': '#dc3545',
                'SKIPPED': '#ffc107', 'COMPLETED': '#0d6efd'
            }

            events.append({
                'timestamp': ts.isoformat() + 'Z' if ts else None,
                'category': 'system',
                'event_type': ex.status.value if ex.status else 'unknown',
                'description': f'{step_name}',
                'step_type': step_type,
                'icon': icon,
                'color': status_colors.get(ex.status.value if ex.status else '', '#999'),
                'error': ex.error_message,
                'details': ex.result_data
            })

        # ActivityLog records
        activities = db.query(ActivityLog).filter_by(participant_id=participant_id).all()
        for a in activities:
            category = 'user' if a.event_type in USER_EVENTS else 'system'

            icon_map = {
                'workflow_started': 'play-circle',
                'form_submitted': 'check2-square',
                'survey_submitted': 'ui-checks',
                'unsubscribed': 'person-x',
                'status_changed': 'arrow-repeat',
                'condition_evaluated': 'shuffle',
                'simulation': 'eye',
                'landing_opened': 'box-arrow-up-right',
                'approval_granted': 'check-circle',
                'approval_rejected': 'x-circle',
            }
            color_map = {
                'workflow_started': '#0d6efd',
                'form_submitted': '#198754',
                'survey_submitted': '#0dcaf0',
                'unsubscribed': '#dc3545',
                'status_changed': '#6c757d',
                'condition_evaluated': '#6c757d',
                'simulation': '#ffc107',
                'landing_opened': '#ff9800',
                'approval_granted': '#198754',
                'approval_rejected': '#dc3545',
            }

            events.append({
                'timestamp': a.created_at.isoformat() + 'Z' if a.created_at else None,
                'category': category,
                'event_type': a.event_type,
                'description': a.description or a.event_type,
                'icon': icon_map.get(a.event_type, 'info-circle'),
                'color': color_map.get(a.event_type, '#999'),
                'details': a.details
            })

        # Sort by timestamp desc
        events.sort(key=lambda e: e['timestamp'] or '', reverse=True)

        return jsonify({
            'participant': {
                'id': participant.id,
                'name': participant.full_name or participant.email,
                'email': participant.email,
                'status': participant.status.value,
                'enrolled_at': participant.enrolled_at.isoformat() + 'Z' if participant.enrolled_at else None,
                'completed_at': participant.completed_at.isoformat() + 'Z' if participant.completed_at else None,
            },
            'events': events
        })

    except Exception as e:
        logger.error(f"Errore timeline: {str(e)}")
        return jsonify({'error': str(e)}), 500


# =============================================
# USER MANAGEMENT (superuser only)
# =============================================

@admin_bp.route('/users')
@superuser_required
def users_list():
    """Lista utenti"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    workflows = db.query(Workflow).order_by(Workflow.name).all()
    return render_template('admin/users.html', users=users, workflows=workflows)


@admin_bp.route('/users/create', methods=['POST'])
@superuser_required
def user_create():
    """Crea nuovo utente"""
    try:
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        is_superuser = request.form.get('is_superuser') == 'on'

        if not username or not password:
            flash('Username and password required', 'danger')
            return redirect(url_for('admin.users_list'))

        if db.query(User).filter_by(username=username).first():
            flash(f'Username "{username}" already exists', 'danger')
            return redirect(url_for('admin.users_list'))

        user = User(username=username, email=email, is_superuser=is_superuser)
        user.set_password(password)
        db.add(user)
        db.commit()

        from app.services.audit_service import log_user_action
        log_user_action('CREATE', 'User', user.id, f'Created user "{username}"')
        flash(f'User "{username}" created', 'success')
        return redirect(url_for('admin.users_list'))

    except Exception as e:
        db.rollback()
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@superuser_required
def user_delete(user_id):
    """Elimina utente"""
    try:
        from flask import g
        user = db.get(User, user_id)
        if not user:
            flash('User not found', 'danger')
        elif user.id == g.user.id:
            flash('Cannot delete yourself', 'danger')
        else:
            uname = user.username
            db.delete(user)
            db.commit()
            from app.services.audit_service import log_user_action
            log_user_action('DELETE', 'User', user_id, f'Deleted user "{uname}"')
            flash(f'User "{uname}" deleted', 'success')
        return redirect(url_for('admin.users_list'))
    except Exception as e:
        db.rollback()
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>/toggle-workflow/<int:workflow_id>', methods=['POST'])
@superuser_required
def toggle_user_workflow(user_id, workflow_id):
    """Assign/remove workflow from user"""
    try:
        user = db.get(User, user_id)
        workflow = db.get(Workflow, workflow_id)
        if not user or not workflow:
            return jsonify({'error': 'Not found'}), 404

        if workflow in user.workflows:
            user.workflows.remove(workflow)
            assigned = False
        else:
            user.workflows.append(workflow)
            assigned = True

        db.commit()
        return jsonify({'assigned': assigned}), 200

    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/onedrive/browse')
def onedrive_browse():
    """Browse OneDrive/SharePoint files via Microsoft Graph API."""
    try:
        import requests as http_requests
        from app.services.email_service import EmailService

        storage = request.args.get('storage', 'onedrive')
        folder_path = request.args.get('path', '')
        sharepoint_site = request.args.get('site', '')

        token = EmailService._get_access_token()
        from_email = current_app.config.get('MAIL_FROM_EMAIL', '')
        headers = {"Authorization": f"Bearer {token}"}

        if storage == 'sharepoint':
            if not sharepoint_site:
                return jsonify({'error': 'SharePoint site required'}), 400
            site_url = f"https://graph.microsoft.com/v1.0/sites/{sharepoint_site.strip('/')}"
            site_resp = http_requests.get(site_url, headers=headers, timeout=15)
            if site_resp.status_code != 200:
                return jsonify({'error': 'SharePoint site not found'}), 404
            site_id = site_resp.json()['id']
            drive_base = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive"
        else:
            drive_base = f"https://graph.microsoft.com/v1.0/users/{from_email}/drive"

        if folder_path:
            url = f"{drive_base}/root:/{folder_path.strip('/')}:/children"
        else:
            url = f"{drive_base}/root/children"

        url += "?$select=name,id,folder,file,size,lastModifiedDateTime&$orderby=name"
        resp = http_requests.get(url, headers=headers, timeout=15)

        if resp.status_code != 200:
            return jsonify({'error': f'Graph API error: {resp.status_code}'}), resp.status_code

        items = []
        for item in resp.json().get('value', []):
            is_folder = 'folder' in item
            is_excel = not is_folder and item.get('name', '').lower().endswith(('.xlsx', '.xls'))
            if is_folder or is_excel:
                items.append({
                    'name': item['name'],
                    'id': item['id'],
                    'type': 'folder' if is_folder else 'file',
                    'size': item.get('size', 0),
                    'modified': item.get('lastModifiedDateTime', '')
                })

        return jsonify({'items': items, 'path': folder_path or '/'})

    except Exception as e:
        logger.error(f"OneDrive browse error: {str(e)}")
        return jsonify({'error': str(e)}), 500
