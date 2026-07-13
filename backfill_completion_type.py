#!/usr/bin/env python3
"""
Backfill completion_type for existing participants.

- participated: has collected_data (form was filled)
- expired: in_progress on a step AFTER the wait_for_landing step, with no collected_data
"""
from app import create_app
from app.models import Participant, WorkflowStep, ParticipantStatus, CompletionType

app = create_app()

with app.app_context():
    from app import db_session as db

    # All participants without completion_type
    participants = db.query(Participant).filter(
        Participant.completion_type.is_(None)
    ).all()

    updated_participated = 0
    updated_expired = 0

    for p in participants:
        # Has collected_data → participated
        if p.collected_data and isinstance(p.collected_data, dict) and len(p.collected_data) > 0:
            # Skip internal-only keys (starting with _)
            real_keys = [k for k in p.collected_data if not k.startswith('_')]
            if real_keys:
                p.completion_type = CompletionType.PARTICIPATED
                updated_participated += 1
                continue

        # In progress, on a step after a wait_for_landing step → expired
        if p.status == ParticipantStatus.IN_PROGRESS and p.current_step_id:
            current_step = db.get(WorkflowStep, p.current_step_id)
            if not current_step:
                continue

            # Check if there's a wait_for_landing step earlier in this workflow
            landing_steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == p.workflow_id,
                WorkflowStep.order < current_step.order,
                WorkflowStep.type == 'email',
            ).all()

            has_earlier_landing = any(
                (s.skip_conditions or {}).get('wait_for_landing')
                for s in landing_steps
            )

            if has_earlier_landing:
                p.completion_type = CompletionType.EXPIRED
                updated_expired += 1

    db.commit()
    print(f"Done. Updated {updated_participated} as participated, {updated_expired} as expired.")
    print(f"Skipped {len(participants) - updated_participated - updated_expired} (no match).")
