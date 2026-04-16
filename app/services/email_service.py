import msal
import requests
from jinja2 import Template
from flask import current_app
import logging

logger = logging.getLogger(__name__)

# Cache token a livello di modulo
_token_cache = msal.SerializableTokenCache()


class EmailService:
    """Servizio invio email via Microsoft Graph API"""

    @staticmethod
    def _get_access_token():
        """Ottiene access token da Microsoft Entra ID"""
        config = current_app.config

        app = msal.ConfidentialClientApplication(
            config['MS_GRAPH_CLIENT_ID'],
            authority=f"https://login.microsoftonline.com/{config['MS_GRAPH_TENANT_ID']}",
            client_credential=config['MS_GRAPH_CLIENT_SECRET'],
            token_cache=_token_cache,
        )

        # Prova prima dalla cache
        result = app.acquire_token_silent(
            scopes=["https://graph.microsoft.com/.default"],
            account=None,
        )

        if not result:
            result = app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )

        if "access_token" in result:
            return result["access_token"]

        error = result.get("error_description", result.get("error", "Errore sconosciuto"))
        raise Exception(f"Impossibile ottenere token Microsoft Graph: {error}")

    @staticmethod
    def send_email(to_email, subject, body_html, body_text=None, from_email=None, from_name=None):
        """
        Invia email tramite Microsoft Graph API

        Args:
            to_email: destinatario
            subject: oggetto
            body_html: corpo HTML
            body_text: corpo plain text (ignorato, Graph usa HTML)
            from_email: mittente (default da config)
            from_name: nome mittente (default da config)

        Returns:
            bool: True se inviato con successo
        """
        try:
            config = current_app.config

            if from_email is None:
                from_email = config['MAIL_FROM_EMAIL']
            if from_name is None:
                from_name = config['MAIL_FROM_NAME']

            token = EmailService._get_access_token()

            # Payload Microsoft Graph
            message = {
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "HTML",
                        "content": body_html
                    },
                    "toRecipients": [
                        {
                            "emailAddress": {
                                "address": to_email
                            }
                        }
                    ]
                },
                "saveToSentItems": "true"
            }

            # Invio tramite Graph API
            response = requests.post(
                f"https://graph.microsoft.com/v1.0/users/{from_email}/sendMail",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=message,
                timeout=30
            )

            if response.status_code == 202:
                logger.info(f"Email inviata a {to_email}: {subject}")
                return True
            else:
                logger.error(
                    f"Errore Graph API ({response.status_code}): {response.text}"
                )
                return False

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
