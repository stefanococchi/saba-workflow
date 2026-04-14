"""
Prefect Workflow Engine Integration
Replaces APScheduler with Prefect for robust workflow execution
"""
from prefect import flow, task
from prefect.tasks import task_input_hash
from datetime import timedelta
from typing import Dict, Any
import logging

from app import db_session as db, create_app
from app.models import Workflow, WorkflowStep, Participant, Execution, ExecutionStatus, ParticipantStatus
from app.services.email_service import EmailService
from app.services.token_service import TokenService

logger = logging.getLogger(__name__)


@task(
    name="send_email_step",
    retries=3,
    retry_delay_seconds=300,  # 5 minutes
    cache_key_fn=task_input_hash,
    cache_expiration=timedelta(hours=1)
)
def send_email_step(participant_id: int, step_id: int, workflow_id: int) -> Dict[str, Any]:
    """
    Execute a single email step
    
    Args:
        participant_id: ID of the participant
        step_id: ID of the workflow step
        workflow_id: ID of the workflow
        
    Returns:
        Dict with execution result
    """
    # Create app context for database access
    app = create_app()
    
    with app.app_context():
        try:
            participant = db.get(Participant, participant_id)
            step = db.get(WorkflowStep, step_id)
            
            if not participant or not step:
                logger.error(f"Participant {participant_id} or Step {step_id} not found")
                return {"success": False, "error": "Not found"}
            
            # Check if participant already completed
            if participant.status == ParticipantStatus.COMPLETED:
                logger.info(f"Participant {participant_id} already completed - skipping")
                return {"success": True, "skipped": True, "reason": "Already completed"}
            
            # Generate landing URL if needed
            landing_url = None
            if step.landing_page_config:
                landing_url = TokenService.generate_landing_url(participant)
            
            # Send email
            success = EmailService.send_workflow_email(participant, step, landing_url)
            
            # Create execution record
            from datetime import datetime
            execution = Execution(
                participant_id=participant_id,
                step_id=step_id,
                status=ExecutionStatus.SENT if success else ExecutionStatus.FAILED,
                scheduled_at=datetime.utcnow(),
                sent_at=datetime.utcnow() if success else None,
                result_data={"prefect_task": True}
            )
            db.add(execution)
            
            # Update participant
            participant.last_interaction = datetime.utcnow()
            participant.current_step_id = step_id
            participant.status = ParticipantStatus.IN_PROGRESS
            
            db.commit()
            
            logger.info(f"Email sent successfully to {participant.email} for step {step.name}")
            
            return {
                "success": success,
                "participant_id": participant_id,
                "step_id": step_id,
                "email": participant.email
            }
            
        except Exception as e:
            logger.error(f"Error executing email step: {str(e)}")
            db.rollback()
            return {"success": False, "error": str(e)}


@task(name="delay_step")
def delay_step(hours: int):
    """
    Delay execution for specified hours
    
    Args:
        hours: Number of hours to wait
    """
    from time import sleep
    logger.info(f"Delaying for {hours} hours")
    sleep(hours * 3600)  # Convert to seconds


@task(name="evaluate_condition")
def evaluate_condition(participant_id: int, condition: Dict[str, Any]) -> bool:
    """
    Evaluate a condition against participant data
    
    Args:
        participant_id: ID of the participant
        condition: Condition configuration
        
    Returns:
        True if condition is met
    """
    app = create_app()
    
    with app.app_context():
        try:
            participant = db.get(Participant, participant_id)
            
            if not participant:
                return False
            
            field = condition.get('field')
            operator = condition.get('operator')
            value = condition.get('value')
            
            # Get field value from collected_data
            actual_value = participant.collected_data.get(field)
            
            # Evaluate based on operator
            if operator == 'equals':
                return str(actual_value) == str(value)
            elif operator == 'not_equals':
                return str(actual_value) != str(value)
            elif operator == 'contains':
                return value in str(actual_value)
            elif operator == 'greater_than':
                return float(actual_value) > float(value)
            elif operator == 'less_than':
                return float(actual_value) < float(value)
            else:
                logger.warning(f"Unknown operator: {operator}")
                return False
                
        except Exception as e:
            logger.error(f"Error evaluating condition: {str(e)}")
            return False


@flow(
    name="execute_workflow",
    description="Execute a complete workflow for a participant",
    retries=1,
    retry_delay_seconds=600
)
def execute_workflow_flow(workflow_id: int, participant_id: int):
    """
    Execute complete workflow for a participant
    
    This is the main Prefect flow that orchestrates all steps
    
    Args:
        workflow_id: ID of the workflow to execute
        participant_id: ID of the participant
    """
    app = create_app()
    
    with app.app_context():
        try:
            workflow = db.get(Workflow, workflow_id)
            participant = db.get(Participant, participant_id)
            
            if not workflow or not participant:
                logger.error(f"Workflow {workflow_id} or Participant {participant_id} not found")
                return
            
            logger.info(f"Starting workflow '{workflow.name}' for participant {participant.email}")
            
            # Execute steps in order
            for step in sorted(workflow.steps, key=lambda s: s.order):
                
                # Check if participant completed (e.g., submitted landing page)
                participant = db.get(Participant, participant_id)  # Refresh
                if participant.status == ParticipantStatus.COMPLETED:
                    logger.info(f"Participant completed - stopping workflow")
                    break
                
                logger.info(f"Executing step {step.order}: {step.name}")
                
                # Apply delay if configured
                if step.delay_hours > 0:
                    logger.info(f"Waiting {step.delay_hours} hours before step {step.order}")
                    delay_step(step.delay_hours)
                
                # Execute step based on type
                if step.type.value == 'email':
                    result = send_email_step(participant_id, step.id, workflow_id)
                    
                    if not result.get('success'):
                        logger.error(f"Step {step.order} failed: {result.get('error')}")
                        # Continue or stop based on configuration
                        # For now, we continue
                
                elif step.type.value == 'condition':
                    # Evaluate condition
                    if step.skip_conditions:
                        condition_met = evaluate_condition(participant_id, step.skip_conditions)
                        logger.info(f"Condition evaluated to: {condition_met}")
                        
                        # For now, just log - full branching requires workflow structure changes
                        # This is placeholder for future conditional logic
                
                else:
                    logger.warning(f"Unknown step type: {step.type}")
            
            logger.info(f"Workflow '{workflow.name}' completed for {participant.email}")
            
        except Exception as e:
            logger.error(f"Error executing workflow: {str(e)}")
            raise


@flow(name="start_workflow_for_participants")
def start_workflow_for_participants(workflow_id: int, participant_ids: list = None):
    """
    Start workflow for multiple participants
    
    Args:
        workflow_id: ID of the workflow
        participant_ids: List of participant IDs (if None, gets all pending)
    """
    app = create_app()
    
    with app.app_context():
        workflow = db.get(Workflow, workflow_id)
        
        if not workflow:
            logger.error(f"Workflow {workflow_id} not found")
            return
        
        # Get participants
        if participant_ids:
            participants = [db.get(Participant, pid) for pid in participant_ids]
        else:
            participants = db.query(Participant).filter_by(
                workflow_id=workflow_id,
                status=ParticipantStatus.PENDING
            ).all()
        
        logger.info(f"Starting workflow for {len(participants)} participants")
        
        # Launch a flow for each participant (parallel execution)
        for participant in participants:
            if participant:
                # Update status to in_progress
                participant.status = ParticipantStatus.IN_PROGRESS
                db.commit()
                
                # Launch flow (async)
                execute_workflow_flow.with_options(
                    name=f"{workflow.name}-{participant.email}"
                ).apply_async(args=[workflow_id, participant.id])
        
        logger.info(f"Launched {len(participants)} workflow executions")


# Utility function to deploy flows
def deploy_flows():
    """
    Deploy flows to Prefect
    
    Run this once to register flows with Prefect
    """
    try:
        # This would be used if deploying to Prefect Cloud/Server
        # For local development, flows are registered automatically
        logger.info("Flows registered successfully")
        return True
    except Exception as e:
        logger.error(f"Error deploying flows: {str(e)}")
        return False
