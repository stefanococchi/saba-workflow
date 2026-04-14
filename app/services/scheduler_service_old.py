from datetime import datetime, timedelta
from app import db_session as db, scheduler
from app.models import Execution, ExecutionStatus, ParticipantStatus, WorkflowStep
from app.services.email_service import EmailService
from app.services.token_service import TokenService
import logging

logger = logging.getLogger(__name__)


class SchedulerService:
    """Servizio scheduling esecuzioni workflow"""
    
    @staticmethod
    def schedule_step(participant, step, delay_hours=0):
        """
        Schedula esecuzione di uno step
        
        Args:
            participant: istanza Participant
            step: istanza WorkflowStep
            delay_hours: ore di delay (default 0 = immediato)
            
        Returns:
            Execution: istanza creata
        """
        try:
            # Calcola timestamp
            scheduled_at = datetime.utcnow() + timedelta(hours=delay_hours)
            
            # Crea execution
            execution = Execution(
                participant_id=participant.id,
                step_id=step.id,
                status=ExecutionStatus.SCHEDULED,
                scheduled_at=scheduled_at
            )
            
            db.add(execution)
            db.flush()  # Ottieni ID
            
            # Job ID univoco
            job_id = f"exec_{execution.id}_{participant.id}_{step.id}"
            execution.job_id = job_id
            
            # Schedula job
            if delay_hours == 0:
                # Esegui immediatamente
                scheduler.add_job(
                    func=SchedulerService._execute_step,
                    args=[execution.id],
                    id=job_id,
                    replace_existing=True
                )
            else:
                # Schedula con delay
                scheduler.add_job(
                    func=SchedulerService._execute_step,
                    args=[execution.id],
                    trigger='date',
                    run_date=scheduled_at,
                    id=job_id,
                    replace_existing=True
                )
            
            db.commit()
            logger.info(f"Schedulato step {step.id} per partecipante {participant.id} tra {delay_hours}h")
            
            return execution
            
        except Exception as e:
            db.rollback()
            logger.error(f"Errore scheduling step: {str(e)}")
            raise
    
    @staticmethod
    def _execute_step(execution_id):
        """
        Esegue uno step (chiamato da scheduler)
        
        Args:
            execution_id: ID esecuzione
        """
        from app import create_app
        
        # Serve app context per operazioni DB
        app = create_app()
        
        with app.app_context():
            try:
                execution = db.get(Execution, execution_id)
                if not execution:
                    logger.error(f"Execution {execution_id} non trovata")
                    return
                
                participant = execution.participant
                step = execution.step
                
                logger.info(f"Esecuzione step {step.id} per partecipante {participant.id}")
                
                # Verifica se partecipante ha già completato
                if participant.status == ParticipantStatus.COMPLETED:
                    execution.status = ExecutionStatus.SKIPPED
                    execution.result_data = {'reason': 'Participant already completed'}
                    db.commit()
                    logger.info(f"Skip: partecipante {participant.id} già completato")
                    return
                
                # Verifica skip conditions
                if SchedulerService._should_skip(participant, step):
                    execution.status = ExecutionStatus.SKIPPED
                    execution.result_data = {'reason': 'Skip conditions met'}
                    db.commit()
                    logger.info(f"Skip: condizioni soddisfatte per step {step.id}")
                    return
                
                # Esegui in base al tipo
                if step.type == 'email':
                    success = SchedulerService._execute_email_step(participant, step, execution)
                else:
                    logger.warning(f"Tipo step {step.type} non supportato")
                    success = False
                
                # Aggiorna stato
                if success:
                    execution.status = ExecutionStatus.SENT
                    execution.sent_at = datetime.utcnow()
                    participant.last_interaction = datetime.utcnow()
                    
                    # Schedula prossimo step se presente
                    SchedulerService._schedule_next_step(participant, step)
                else:
                    execution.status = ExecutionStatus.FAILED
                    execution.error_message = "Invio fallito"
                
                db.commit()
                
            except Exception as e:
                logger.error(f"Errore esecuzione step {execution_id}: {str(e)}")
                db.rollback()
    
    @staticmethod
    def _execute_email_step(participant, step, execution):
        """
        Esegue step email
        
        Returns:
            bool: successo
        """
        try:
            # Genera landing URL se step lo richiede
            landing_url = None
            if step.landing_page_config:
                landing_url = TokenService.generate_landing_url(participant)
            
            # Invia email
            success = EmailService.send_workflow_email(participant, step, landing_url)
            
            return success
            
        except Exception as e:
            logger.error(f"Errore email step: {str(e)}")
            return False
    
    @staticmethod
    def _should_skip(participant, step):
        """
        Verifica se step deve essere skippato
        
        Args:
            participant: istanza Participant
            step: istanza WorkflowStep
            
        Returns:
            bool: True se skip
        """
        # TODO: implementare logica skip_conditions con JSONLogic
        # Per ora ritorna sempre False
        return False
    
    @staticmethod
    def _schedule_next_step(participant, current_step):
        """
        Schedula il prossimo step in sequenza
        
        Args:
            participant: istanza Participant
            current_step: step appena completato
        """
        try:
            # Trova prossimo step
            next_step = db.query(WorkflowStep).filter_by(
                workflow_id=current_step.workflow_id,
                order=current_step.order + 1
            ).first()
            
            if next_step:
                # Schedula con delay configurato
                SchedulerService.schedule_step(
                    participant,
                    next_step,
                    delay_hours=next_step.delay_hours
                )
                
                # Aggiorna current step partecipante
                participant.current_step_id = next_step.id
                participant.status = ParticipantStatus.IN_PROGRESS
                db.commit()
                
                logger.info(f"Schedulato next step {next_step.id} per partecipante {participant.id}")
            else:
                logger.info(f"Nessun next step per partecipante {participant.id}")
                
        except Exception as e:
            logger.error(f"Errore scheduling next step: {str(e)}")
    
    @staticmethod
    def cancel_scheduled_executions(participant_id):
        """
        Cancella tutte le esecuzioni schedulate per un partecipante
        
        Args:
            participant_id: ID partecipante
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
                        logger.info(f"Cancellato job {execution.job_id}")
                    except Exception as e:
                        logger.warning(f"Job {execution.job_id} non trovato: {str(e)}")
                
                execution.status = ExecutionStatus.SKIPPED
                execution.result_data = {'reason': 'Cancelled by user action'}
            
            db.commit()
            logger.info(f"Cancellate {len(executions)} esecuzioni per partecipante {participant_id}")
            
        except Exception as e:
            logger.error(f"Errore cancellazione executions: {str(e)}")
            db.rollback()
