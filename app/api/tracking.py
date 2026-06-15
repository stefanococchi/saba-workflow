"""Client tracking blueprint — read-only workflow status for external clients."""

from flask import Blueprint, render_template, session, g, jsonify
from app import db_session as db
from app.models import (
    Workflow, Participant, Execution, ActivityLog, WorkflowStep,
    ParticipantStatus, ExecutionStatus, User, UserRole
)
from app.api.auth import client_login_required, get_current_user
import logging

logger = logging.getLogger(__name__)

tracking_bp = Blueprint('tracking', __name__, url_prefix='/tracking')


@tracking_bp.before_request
def _load_user():
    from flask import redirect, url_for
    if not session.get('user_id'):
        return redirect(url_for('auth.login'))
    g.user = get_current_user()
    if not g.user:
        session.clear()
        return redirect(url_for('auth.login'))


def _get_user_workflows():
    """Return workflows accessible to the current user."""
    user = g.user
    if user.role == UserRole.SUPERUSER or user.is_superuser:
        return db.query(Workflow).order_by(Workflow.name).all()
    return list(user.workflows)


@tracking_bp.route('/')
def index():
    """Main tracking page — list of assigned workflows."""
    workflows = _get_user_workflows()

    # Build summary stats per workflow
    wf_stats = []
    for wf in workflows:
        participants = db.query(Participant).filter_by(workflow_id=wf.id).all()
        total = len(participants)
        completed = sum(1 for p in participants if p.status == ParticipantStatus.COMPLETED)
        in_progress = sum(1 for p in participants if p.status == ParticipantStatus.IN_PROGRESS)
        pending = sum(1 for p in participants if p.status == ParticipantStatus.PENDING)
        bounced = sum(1 for p in participants if p.status in (ParticipantStatus.BOUNCED, ParticipantStatus.UNSUBSCRIBED))

        wf_stats.append({
            'workflow': wf,
            'total': total,
            'completed': completed,
            'in_progress': in_progress,
            'pending': pending,
            'bounced': bounced,
            'pct': round(completed / total * 100) if total > 0 else 0,
        })

    return render_template('tracking/index.html', wf_stats=wf_stats, user=g.user)


@tracking_bp.route('/workflow/<int:workflow_id>')
def workflow_detail(workflow_id):
    """Workflow detail — participants, status flow, execution timeline."""
    # Check access
    workflows = _get_user_workflows()
    wf = next((w for w in workflows if w.id == workflow_id), None)
    if not wf:
        return render_template('tracking/not_found.html'), 404

    steps = sorted(wf.steps, key=lambda s: s.order)
    participants = db.query(Participant).filter_by(workflow_id=workflow_id).order_by(Participant.id).all()

    # Build next step info per participant
    # 1. Check for scheduled executions first
    scheduled_execs = (
        db.query(Execution)
        .join(Participant)
        .join(WorkflowStep)
        .filter(
            Participant.workflow_id == workflow_id,
            Execution.status == ExecutionStatus.SCHEDULED,
        )
        .order_by(Execution.scheduled_at)
        .all()
    )
    next_step_map = {}  # participant_id -> {step_name, scheduled_at}
    for ex in scheduled_execs:
        if ex.participant_id not in next_step_map:
            next_step_map[ex.participant_id] = {
                'step_name': ex.step.name if ex.step else '?',
                'scheduled_at': ex.scheduled_at,
            }

    # 2. For participants without a scheduled execution, show the next step by order
    #    Also calculate timeout/expiry for current step
    from datetime import timedelta
    step_by_id = {s.id: s for s in steps}
    timeout_map = {}  # participant_id -> {timeout_at, if_timeout, if_timeout_step_name}

    for p in participants:
        # Calculate timeout for current step
        if p.current_step_id and p.current_step_id in step_by_id and p.status == ParticipantStatus.IN_PROGRESS:
            current = step_by_id[p.current_step_id]
            config = current.skip_conditions or {}
            timeout_days = config.get('landing_timeout_days', 7) if config.get('wait_for_landing') else None

            if timeout_days:
                # Find when email was sent for this step
                last_exec = (
                    db.query(Execution)
                    .filter_by(participant_id=p.id, step_id=current.id)
                    .filter(Execution.status.in_([
                        ExecutionStatus.SENT, ExecutionStatus.DELIVERED,
                        ExecutionStatus.OPENED, ExecutionStatus.CLICKED,
                    ]))
                    .order_by(Execution.sent_at.desc())
                    .first()
                )
                if last_exec and last_exec.sent_at:
                    timeout_at = last_exec.sent_at + timedelta(days=timeout_days)
                    if_timeout = config.get('landing_if_timeout', 'continue')
                    if_timeout_step = config.get('landing_if_timeout_step', 0)
                    timeout_step_name = None
                    if if_timeout == 'jump' and if_timeout_step:
                        ts = next((s for s in steps if s.order == if_timeout_step), None)
                        timeout_step_name = ts.name if ts else f'Step {if_timeout_step}'
                    elif if_timeout == 'continue':
                        ns = next((s for s in steps if s.order > current.order), None)
                        timeout_step_name = ns.name if ns else 'End'

                    timeout_map[p.id] = {
                        'timeout_at': timeout_at,
                        'if_timeout': if_timeout,
                        'timeout_step_name': timeout_step_name,
                    }

        # Next step by order (for participants without scheduled execution)
        if p.id in next_step_map:
            continue
        if p.status == ParticipantStatus.COMPLETED or p.status == ParticipantStatus.PENDING:
            continue
        if p.current_step_id and p.current_step_id in step_by_id:
            current = step_by_id[p.current_step_id]
            next_s = next((s for s in steps if s.order > current.order), None)
            if next_s:
                next_step_map[p.id] = {
                    'step_name': next_s.name,
                    'scheduled_at': None,
                }

    return render_template('tracking/workflow_detail.html',
                           workflow=wf, steps=steps, participants=participants,
                           next_step_map=next_step_map, timeout_map=timeout_map, user=g.user)


@tracking_bp.route('/api/workflow/<int:workflow_id>/timeline')
def api_timeline(workflow_id):
    """JSON API — execution timeline for a workflow."""
    # Check access
    workflows = _get_user_workflows()
    wf = next((w for w in workflows if w.id == workflow_id), None)
    if not wf:
        return jsonify({'error': 'Not found'}), 404

    # Get all executions + activity logs
    executions = (
        db.query(Execution)
        .join(Participant)
        .filter(Participant.workflow_id == workflow_id)
        .order_by(Execution.scheduled_at.desc())
        .all()
    )

    activities = (
        db.query(ActivityLog)
        .filter_by(workflow_id=workflow_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(500)
        .all()
    )

    timeline = []

    for ex in executions:
        p = ex.participant
        step = ex.step
        timeline.append({
            'type': 'execution',
            'time': (ex.sent_at or ex.scheduled_at).isoformat() if (ex.sent_at or ex.scheduled_at) else None,
            'participant': ((p.first_name or '') + ' ' + (p.last_name or '')).strip() or p.email or f'#{p.id}',
            'participant_id': p.id,
            'step': step.name if step else '?',
            'step_order': step.order if step else 0,
            'status': ex.status.value,
            'error': ex.error_message,
        })

    for act in activities:
        # Skip duplicates that are already covered by executions
        if act.event_type in ('email_scheduled',):
            continue
        p = db.get(Participant, act.participant_id) if act.participant_id else None
        step = db.get(WorkflowStep, act.step_id) if act.step_id else None
        p_name = ''
        if p:
            p_name = ((p.first_name or '') + ' ' + (p.last_name or '')).strip() or p.email or f'#{p.id}'
        timeline.append({
            'type': 'activity',
            'time': act.created_at.isoformat() if act.created_at else None,
            'participant': p_name,
            'participant_id': act.participant_id,
            'step': step.name if step else '',
            'step_order': step.order if step else 0,
            'event_type': act.event_type,
            'description': act.description,
            'status': act.event_type,
        })

    # Sort by time descending
    timeline.sort(key=lambda x: x.get('time') or '', reverse=True)

    return jsonify(timeline[:500])


@tracking_bp.route('/api/workflow/<int:workflow_id>/status-flow')
def api_status_flow(workflow_id):
    """JSON API — status flow funnel per step."""
    workflows = _get_user_workflows()
    wf = next((w for w in workflows if w.id == workflow_id), None)
    if not wf:
        return jsonify({'error': 'Not found'}), 404

    steps = sorted(wf.steps, key=lambda s: s.order)
    participants = db.query(Participant).filter_by(workflow_id=workflow_id).all()

    SUBSTATE_RANK = {
        'failed': 0, 'skipped': 0, 'scheduled': 1, 'sent': 2, 'delivered': 2,
        'opened': 3, 'clicked': 4, 'landing_opened': 5,
        'form_submitted': 6, 'survey_submitted': 6, 'completed': 7,
    }

    # Build a set of participant IDs currently at each step
    # Completed participants go to a virtual "completed" bucket
    pids_at_step = {}  # step_id -> set of participant_ids
    pids_completed = set()
    pids_pending = set()
    for p in participants:
        if p.status == ParticipantStatus.COMPLETED:
            pids_completed.add(p.id)
        elif p.status == ParticipantStatus.PENDING:
            pids_pending.add(p.id)
        elif p.current_step_id:
            pids_at_step.setdefault(p.current_step_id, set()).add(p.id)

    flow = []
    for step in steps:
        # Only count participants whose current step is this one
        current_pids = pids_at_step.get(step.id, set())

        # For those participants, find their best substate at this step
        step_execs = db.query(Execution).filter_by(step_id=step.id).all()
        step_activities = db.query(ActivityLog).filter_by(step_id=step.id).all()

        best = {}  # participant_id -> best_status
        for ex in step_execs:
            if ex.participant_id not in current_pids:
                continue
            cur = best.get(ex.participant_id, '')
            if SUBSTATE_RANK.get(ex.status.value, 0) > SUBSTATE_RANK.get(cur, -1):
                best[ex.participant_id] = ex.status.value

        for act in step_activities:
            if not act.participant_id or act.participant_id not in current_pids:
                continue
            cur = best.get(act.participant_id, '')
            evt = act.event_type.replace('email_', '')  # normalize
            if SUBSTATE_RANK.get(evt, 0) > SUBSTATE_RANK.get(cur, -1):
                best[act.participant_id] = evt

        # Participants at this step with no execution yet → scheduled
        for pid in current_pids:
            if pid not in best:
                best[pid] = 'scheduled'

        # Count substates
        counts = {}
        for pid, st in best.items():
            if st == 'delivered':
                st = 'sent'
            counts[st] = counts.get(st, 0) + 1

        flow.append({
            'step_order': step.order,
            'step_name': step.name,
            'step_type': step.type.value,
            'total': len(current_pids),
            'substates': counts,
        })

    return jsonify({
        'steps': flow,
        'total_participants': len(participants),
        'pending': len(pids_pending),
        'completed': len(pids_completed),
    })
