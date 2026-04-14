import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Template
from flask import current_app
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Servizio invio email via SMTP"""
    
    @staticmethod
    def send_email(to_email, subject, body_html, body_text=None, from_email=None, from_name=None):
        """
        Invia email
        
        Args:
            to_email: destinatario
            subject: oggetto
            body_html: corpo HTML
            body_text: corpo plain text (opzionale)
            from_email: mittente (default da config)
            from_name: nome mittente (default da config)
            
        Returns:
            bool: True se inviato con successo
        """
        try:
            config = current_app.config
            
            # Default values
            if from_email is None:
                from_email = config['SMTP_FROM_EMAIL']
            if from_name is None:
                from_name = config['SMTP_FROM_NAME']
            
            # Crea messaggio
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{from_name} <{from_email}>"
            msg['To'] = to_email
            
            # Aggiungi parti
            if body_text:
                part1 = MIMEText(body_text, 'plain', 'utf-8')
                msg.attach(part1)
            
            part2 = MIMEText(body_html, 'html', 'utf-8')
            msg.attach(part2)
            
            # Connessione SMTP
            with smtplib.SMTP(config['SMTP_HOST'], config['SMTP_PORT'], timeout=10) as server:
                if config['SMTP_USE_TLS']:
                    server.starttls()
                
                if config['SMTP_USER'] and config['SMTP_PASSWORD']:
                    server.login(config['SMTP_USER'], config['SMTP_PASSWORD'])
                
                server.send_message(msg)
            
            logger.info(f"Email inviata a {to_email}: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Errore invio email a {to_email}: {str(e)}")
            return False
    
    @staticmethod
    def render_template(template_string, context):
        """
        Renderizza template Jinja2
        
        Args:
            template_string: template Jinja2
            context: variabili per il template
            
        Returns:
            str: template renderizzato
        """
        try:
            template = Template(template_string)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Errore rendering template: {str(e)}")
            raise
    
    @staticmethod
    def send_workflow_email(participant, step, landing_url=None):
        """
        Invia email per uno step del workflow
        
        Args:
            participant: istanza Participant
            step: istanza WorkflowStep
            landing_url: URL landing page (se presente)
            
        Returns:
            bool: successo invio
        """
        try:
            # Context per template
            context = {
                'participant': {
                    'name': participant.full_name,
                    'first_name': participant.first_name,
                    'last_name': participant.last_name,
                    'email': participant.email,
                },
                'landing_url': landing_url or '',
                'workflow_name': participant.workflow.name,
                'evento': participant.workflow.name,
                'step_name': step.name,
            }
            
            # Aggiungi dati custom dal workflow config
            if participant.workflow.config:
                context.update(participant.workflow.config)
            
            # Renderizza body
            body_html = EmailService.render_template(step.body_template, context)
            
            # Renderizza subject
            subject = EmailService.render_template(step.subject, context)
            
            # Invia
            return EmailService.send_email(
                to_email=participant.email,
                subject=subject,
                body_html=body_html
            )
            
        except Exception as e:
            logger.error(f"Errore invio workflow email: {str(e)}")
            return False
