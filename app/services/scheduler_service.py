from datetime import datetime, timedelta
from app import db_session as db, scheduler
from app.models import Execution, ExecutionStatus, ParticipantStatus, WorkflowStep
from app.services.email_service import EmailService
from app.services.token_service import TokenService
import logging

logger = logging.getLogger(__name__)


class SchedulerService:
    """Enhanced Scheduler Service with wait_until support"""
    
    @staticmethod
    def schedule_step(participant, step, delay_hours=0):
        """
        Schedule execution of a step
        
        Supports:
        - delay_hours: Wait X hours before execution
        - wait_until: Wait until specific date/time (for wait_until step type)
        
        Args:
            participant: Participant instance
            step: WorkflowStep instance
            delay_hours: Hours to delay (default 0 = immediate)
            
        Returns:
            Execution instance
        """
        try:
            # Calculate scheduled time
            scheduled_at = None
            
            # Check if this is a wait_until step
            if step.type.value == 'wait_until':
                scheduled_at = SchedulerService._calculate_wait_until(step)
                logger.info(f"Wait Until step calculated: {scheduled_at}")
            else:
                # Regular delay
                scheduled_at = datetime.utcnow() + timedelta(hours=delay_hours)
            
            # Create execution record
            execution = Execution(
                participant_id=participant.id,
                step_id=step.id,
                status=ExecutionStatus.SCHEDULED,
                scheduled_at=scheduled_at
            )
            
            db.add(execution)
            db.flush()  # Get ID
            
            # Unique job ID
            job_id = f"exec_{execution.id}_{participant.id}_{step.id}"
            execution.job_id = job_id
            
            # Schedule job
            now = datetime.utcnow()
            if scheduled_at <= now:
                # Execute immediately
                scheduler.add_job(
                    func=SchedulerService._execute_step,
                    args=[execution.id],
                    id=job_id,
                    replace_existing=True
                )
                logger.info(f"✓ Scheduled step {step.id} for immediate execution")
            else:
                # Schedule with delay
                scheduler.add_job(
                    func=SchedulerService._execute_step,
                    args=[execution.id],
                    trigger='date',
                    run_date=scheduled_at,
                    id=job_id,
                    replace_existing=True
                )
                time_until = (scheduled_at - now).total_seconds() / 3600
                logger.info(f"✓ Scheduled step {step.id} for {scheduled_at} ({time_until:.1f}h from now)")
            
            db.commit()
            
            return execution
            
        except Exception as e:
            db.rollback()
            logger.error(f"✗ Error scheduling step: {str(e)}")
            raise
    
    @staticmethod
    def _calculate_wait_until(step):
        """
        Calculate target datetime for wait_until step
        
        Args:
            step: WorkflowStep with wait_until configuration
            
        Returns:
            datetime: Target execution time (UTC)
        """
        from datetime import datetime
        
        # Get configuration from skip_conditions (used for storing step config)
        config = step.skip_conditions or {}
        wait_type = config.get('wait_type', 'date')
        
        # For simplicity, ignore timezone for now (assume UTC)
        # In production, you'd use pytz here
        
        now_utc = datetime.utcnow()
        
        if wait_type == 'date':
            # Wait until specific date and time
            target_date = config.get('target_date')  # YYYY-MM-DD
            target_time = config.get('target_time', '09:00')  # HH:MM
            
            if not target_date:
                logger.warning("No target_date specified for wait_until, using current time")
                return now_utc
            
            try:
                # Parse datetime
                datetime_str = f"{target_date} {target_time}"
                target_dt = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
                
                # If target is in the past, execute immediately
                if target_dt < now_utc:
                    logger.warning(f"Target date {target_dt} is in the past, executing immediately")
                    return now_utc
                
                return target_dt
                
            except ValueError as e:
                logger.error(f"Error parsing wait_until date: {e}")
                return now_utc
            
        elif wait_type == 'time':
            # Wait until specific time today (or tomorrow if already passed)
            target_time = config.get('target_time', '09:00')  # HH:MM
            
            try:
                hour, minute = map(int, target_time.split(':'))
                
                target_dt = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # If time already passed today, schedule for tomorrow
                if target_dt <= now_utc:
                    target_dt += timedelta(days=1)
                
                return target_dt
                
            except (ValueError, AttributeError) as e:
                logger.error(f"Error parsing time: {e}")
                return now_utc
            
        elif wait_type == 'day_of_week':
            # Wait until next occurrence of specific day
            target_day = config.get('target_day', 'monday').lower()
            target_time = config.get('target_time', '09:00')
            
            days_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                'friday': 4, 'saturday': 5, 'sunday': 6
            }
            
            target_weekday = days_map.get(target_day, 0)
            current_weekday = now_utc.weekday()
            
            # Calculate days until target
            days_ahead = target_weekday - current_weekday
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            
            target_dt = now_utc + timedelta(days=days_ahead)
            
            try:
                hour, minute = map(int, target_time.split(':'))
                target_dt = target_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return target_dt
            except (ValueError, AttributeError) as e:
                logger.error(f"Error parsing time for day_of_week: {e}")
                return now_utc
        
        else:
            logger.warning(f"Unknown wait_type: {wait_type}, executing immediately")
            return now_utc
    
    @staticmethod
    def _execute_step(execution_id):
        """
        Execute a step (called by scheduler)
        
        Args:
            execution_id: Execution ID
        """
        from app import create_app
        
        # Need app context for DB operations
        app = create_app()
        
        with app.app_context():
            try:
                execution = db.get(Execution, execution_id)
                if not execution:
                    logger.error(f"✗ Execution {execution_id} not found")
                    return
                
                participant = execution.participant
                step = execution.step
                
                logger.info(f"▶ Executing step {step.id} for participant {participant.id}")
                
                # Check if participant already completed
                if participant.status == ParticipantStatus.COMPLETED:
                    execution.status = ExecutionStatus.SKIPPED
                    execution.result_data = {'reason': 'Participant already completed'}
                    db.commit()
                    logger.info(f"⊘ Skipped: participant {participant.id} already completed")
                    return
                
                # Check skip conditions
                if SchedulerService._should_skip(participant, step):
                    execution.status = ExecutionStatus.SKIPPED
                    execution.result_data = {'reason': 'Skip conditions met'}
                    db.commit()
                    logger.info(f"⊘ Skipped: conditions met for step {step.id}")
                    return
                
                # Execute based on type
                success = False
                
                if step.type.value == 'email':
                    success = SchedulerService._execute_email_step(participant, step, execution)
                elif step.type.value == 'wait_until':
                    # Wait until step just triggers next step
                    success = True
                    logger.info(f"✓ Wait Until step completed, triggering next step")
                elif step.type.value == 'goal_check':
                    # Goal check step
                    success = SchedulerService._execute_goal_check_step(participant, step, execution)
                elif step.type.value == 'export_data':
                    # Export data step
                    success = SchedulerService._execute_export_data_step(participant, step, execution)
                else:
                    logger.warning(f"⚠ Unsupported step type: {step.type}")
                
                # Update status
                if success:
                    execution.status = ExecutionStatus.SENT
                    execution.sent_at = datetime.utcnow()
                    participant.last_interaction = datetime.utcnow()
                    
                    # Schedule next step
                    SchedulerService._schedule_next_step(participant, step)
                else:
                    execution.status = ExecutionStatus.FAILED
                    execution.error_message = "Execution failed"
                
                db.commit()
                
            except Exception as e:
                logger.error(f"✗ Error executing step {execution_id}: {str(e)}")
                db.rollback()
    
    @staticmethod
    def _execute_email_step(participant, step, execution):
        """
        Execute email step
        
        Returns:
            bool: success
        """
        try:
            # Generate landing URL if step requires it
            landing_url = None
            if step.landing_page_config:
                landing_url = TokenService.generate_landing_url(participant)
            
            # Send email
            success = EmailService.send_workflow_email(participant, step, landing_url)
            
            return success
            
        except Exception as e:
            logger.error(f"✗ Email error: {str(e)}")
            return False
    
    @staticmethod
    def _execute_goal_check_step(participant, step, execution):
        """
        Execute goal check step
        
        Checks if participant reached goal. If yes, completes workflow.
        
        Returns:
            bool: success (always True for goal check)
        """
        try:
            # Get goal configuration from skip_conditions
            config = step.skip_conditions or {}
            goal_type = config.get('goal', 'form_submitted')
            action_if_met = config.get('if_met', 'complete')
            action_if_not_met = config.get('if_not_met', 'continue')
            
            # Check if goal is met
            goal_met = SchedulerService._check_goal(participant, goal_type, config)
            
            execution.result_data = {
                'goal_type': goal_type,
                'goal_met': goal_met,
                'action_taken': action_if_met if goal_met else action_if_not_met
            }
            
            if goal_met:
                logger.info(f"✓ Goal '{goal_type}' MET for participant {participant.id}")
                
                if action_if_met == 'complete':
                    # Cancel all future scheduled executions
                    SchedulerService.cancel_scheduled_executions(participant.id)
                    
                    # Mark participant as completed
                    participant.status = ParticipantStatus.COMPLETED
                    db.commit()
                    
                    logger.info(f"✓ Workflow COMPLETED for participant {participant.id}")
                    
                    # Don't schedule next step
                    return True
                    
            else:
                logger.info(f"⊘ Goal '{goal_type}' NOT MET for participant {participant.id}, continuing workflow")
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Goal check error: {str(e)}")
            return False
    
    @staticmethod
    def _check_goal(participant, goal_type, config):
        """
        Check if participant reached specific goal
        
        Args:
            participant: Participant instance
            goal_type: Type of goal to check
            config: Goal configuration
            
        Returns:
            bool: True if goal is met
        """
        try:
            if goal_type == 'form_submitted':
                # Check if participant submitted landing page form
                return participant.collected_data is not None and len(participant.collected_data) > 0
                
            elif goal_type == 'field_filled':
                # Check if specific field is filled
                field_name = config.get('field_name')
                if not field_name or not participant.collected_data:
                    return False
                return field_name in participant.collected_data and participant.collected_data[field_name]
                
            elif goal_type == 'field_equals':
                # Check if field equals specific value
                field_name = config.get('field_name')
                expected_value = config.get('field_value')
                if not field_name or not participant.collected_data:
                    return False
                return participant.collected_data.get(field_name) == expected_value
                
            elif goal_type == 'email_opened':
                # Check if participant opened any email (has interaction)
                return participant.last_interaction is not None
                
            elif goal_type == 'status_equals':
                # Check participant status
                expected_status = config.get('status_value', 'completed')
                return participant.status.value == expected_status
                
            else:
                logger.warning(f"Unknown goal type: {goal_type}")
                return False
                
        except Exception as e:
            logger.error(f"Error checking goal: {str(e)}")
            return False
    
    @staticmethod
    def _execute_export_data_step(participant, step, execution):
        """
        Execute export data step
        
        Exports all workflow participants to CSV and sends via email
        
        Returns:
            bool: success
        """
        try:
            from app.services.export_service import ExportService
            
            # Get export configuration from skip_conditions
            config = step.skip_conditions or {}
            export_format = config.get('format', 'csv')
            send_to = config.get('send_to', '')
            save_local = config.get('save_local', False)
            
            workflow_id = step.workflow_id
            
            logger.info(f"▶ Exporting workflow {workflow_id} data (format: {export_format})")
            
            if export_format == 'csv':
                success, csv_content, filename = ExportService.export_workflow_csv(
                    workflow_id=workflow_id,
                    send_to_email=send_to if send_to else None
                )
                
                if success:
                    execution.result_data = {
                        'format': export_format,
                        'filename': filename,
                        'sent_to': send_to,
                        'rows_exported': csv_content.count('\n') - 1 if csv_content else 0
                    }
                    
                    # Save locally if requested
                    if save_local and csv_content:
                        ExportService.save_csv_file(csv_content, filename)
                    
                    logger.info(f"✓ Export completed: {filename}")
                    return True
                else:
                    logger.error(f"✗ Export failed for workflow {workflow_id}")
                    return False
            else:
                logger.warning(f"Unsupported export format: {export_format}")
                return False
                
        except Exception as e:
            logger.error(f"✗ Export data error: {str(e)}")
            return False
    
    @staticmethod
    def _should_skip(participant, step):
        """
        Check if step should be skipped based on conditions
        
        Args:
            participant: Participant instance
            step: WorkflowStep instance
            
        Returns:
            bool: True if should skip
        """
        # TODO: Implement JSONLogic for skip_conditions
        # For now, always returns False
        return False
    
    @staticmethod
    def _schedule_next_step(participant, current_step):
        """
        Schedule next step in sequence
        
        Args:
            participant: Participant instance
            current_step: Just completed WorkflowStep
        """
        try:
            # Find next step
            next_step = db.query(WorkflowStep).filter_by(
                workflow_id=current_step.workflow_id,
                order=current_step.order + 1
            ).first()
            
            if next_step:
                # Schedule with configured delay
                SchedulerService.schedule_step(
                    participant,
                    next_step,
                    delay_hours=next_step.delay_hours
                )
                
                # Update participant current step
                participant.current_step_id = next_step.id
                participant.status = ParticipantStatus.IN_PROGRESS
                db.commit()
                
                logger.info(f"→ Scheduled next step {next_step.id} for participant {participant.id}")
            else:
                logger.info(f"✓ Workflow completed for participant {participant.id} (no more steps)")
                
        except Exception as e:
            logger.error(f"✗ Error scheduling next step: {str(e)}")
    
    @staticmethod
    def cancel_scheduled_executions(participant_id):
        """
        Cancel all scheduled executions for a participant
        
        Args:
            participant_id: Participant ID
        """
        try:
            executions = db.query(Execution).filter_by(
                participant_id=participant_id,
                status=ExecutionStatus.SCHEDULED
            ).all()
            
            for execution in executions:
                if execution.job_id:
                    try:
                        scheduler.remove_job(execution.job_id)
                        logger.info(f"✓ Cancelled job {execution.job_id}")
                    except Exception as e:
                        logger.warning(f"⚠ Job {execution.job_id} not found: {str(e)}")
                
                execution.status = ExecutionStatus.SKIPPED
                execution.result_data = {'reason': 'Cancelled by user action'}
            
            db.commit()
            logger.info(f"✓ Cancelled {len(executions)} executions for participant {participant_id}")
            
        except Exception as e:
            logger.error(f"✗ Error cancelling executions: {str(e)}")
            db.rollback()
