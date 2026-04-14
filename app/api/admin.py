from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db_session as db
from app.models import Workflow, WorkflowStep, Participant, Execution, ActivityLog, WorkflowStatus, ParticipantStatus, ExecutionStatus
from sqlalchemy import func
import logging

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


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
        
        # Workflows recenti
        recent_workflows = db.query(Workflow).order_by(
            Workflow.created_at.desc()
        ).limit(5).all()

        # Attività recenti (log unificato)
        recent_activities = db.query(ActivityLog).order_by(
            ActivityLog.created_at.desc()
        ).limit(10).all()

        return render_template('admin/dashboard.html',
                             stats=stats,
                             workflow_status_labels=workflow_status_labels,
                             workflow_status_data=workflow_status_data,
                             participant_status_labels=participant_status_labels,
                             participant_status_data=participant_status_data,
                             recent_workflows=recent_workflows,
                             recent_activities=recent_activities)

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
                             recent_activities=[])


@admin_bp.route('/workflows')
def workflows_list():
    """Lista tutti i workflows"""
    try:
        # Filtri
        status_filter = request.args.get('status')
        
        query = db.query(Workflow)
        
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
        
        query = db.query(Participant)
        
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

        query = db.query(Participant).filter(
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
        
        query = db.query(Execution).join(Participant)
        
        if workflow_id:
            query = query.filter(Participant.workflow_id == workflow_id)
        
        executions = query.order_by(Execution.scheduled_at.desc()).all()

        # Activity Log
        activity_query = db.query(ActivityLog)
        if workflow_id:
            activity_query = activity_query.filter(ActivityLog.workflow_id == workflow_id)
        activities = activity_query.order_by(ActivityLog.created_at.desc()).all()

        # Unifica in una timeline
        timeline = []
        for ex in executions:
            wf_name = ''
            if ex.participant and ex.participant.workflow:
                wf_name = ex.participant.workflow.name
            timeline.append({
                'type': 'execution',
                'entry_id': ex.id,
                'participant_id': ex.participant_id,
                'time': ex.scheduled_at,
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
