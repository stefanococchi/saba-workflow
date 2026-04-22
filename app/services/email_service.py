import base64
import re
import uuid
import msal
import requests
from jinja2 import Template
from flask import current_app
import logging

logger = logging.getLogger(__name__)

# Cache token a livello di modulo
_token_cache = msal.SerializableTokenCache()

# Regex per trovare immagini base64 nell'HTML
_BASE64_IMG_RE = re.compile(
    r'(<img\s[^>]*?)src="data:image/([\w+]+);base64,([^"]+)"',
    re.IGNORECASE
)


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
    def _extract_inline_images(body_html):
        """
        Estrae immagini base64 dall'HTML e le converte in allegati inline (cid:).

        Returns:
            tuple: (html_modificato, lista_allegati)
        """
        attachments = []

        def replace_match(match):
            prefix = match.group(1)
            img_type = match.group(2)
            b64_data = match.group(3)

            content_id = str(uuid.uuid4()).replace('-', '')[:16]

            # Mappa tipo immagine → content type
            content_type_map = {
                'png': 'image/png',
                'jpeg': 'image/jpeg',
                'jpg': 'image/jpeg',
                'gif': 'image/gif',
                'webp': 'image/webp',
                'svg+xml': 'image/svg+xml',
            }
            content_type = content_type_map.get(img_type.lower(), f'image/{img_type}')

            attachments.append({
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": f"image_{content_id}.{img_type.split('+')[0]}",
                "contentType": content_type,
                "contentBytes": b64_data,
                "contentId": content_id,
                "isInline": True
            })

            return f'{prefix}src="cid:{content_id}"'

        modified_html = _BASE64_IMG_RE.sub(replace_match, body_html)
        return modified_html, attachments

    @staticmethod
    def send_email(to_email, subject, body_html, body_text=None, from_email=None, from_name=None, file_attachments=None):
        """
        Invia email tramite Microsoft Graph API.
        Le immagini base64 nel body vengono convertite automaticamente
        in allegati inline (cid:).

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

            # Estrai immagini base64 e converti in allegati inline
            body_html, inline_attachments = EmailService._extract_inline_images(body_html)

            # Payload Microsoft Graph
            message = {
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "HTML",
                        "content": body_html
                    },
                    "toRecipients": [
                        {"emailAddress": {"address": addr.strip()}}
                        for addr in str(to_email).replace(';', ',').split(',')
                        if addr.strip()
                    ]
                },
                "saveToSentItems": "true"
            }

            # Aggiungi allegati file se presenti
            all_attachments = list(inline_attachments)
            if file_attachments:
                for att in file_attachments:
                    all_attachments.append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": att.filename,
                        "contentType": att.mime_type,
                        "contentBytes": base64.b64encode(att.data).decode('utf-8'),
                        "isInline": False
                    })

            if all_attachments:
                message["message"]["attachments"] = all_attachments

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
                logger.info(f"Email inviata a {to_email}: {subject} ({len(inline_attachments)} immagini inline)")
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
            import re
            # 1. Remove HTML tags INSIDE Jinja2 variables (e.g. {{ participant.<b>first</b>_name }})
            def _clean_var(m):
                inner = re.sub(r'<[^>]+>', '', m.group(0))
                return inner
            template_string = re.sub(r'\{\{.*?\}\}', _clean_var, template_string, flags=re.DOTALL)

            # 2. Remove wrapping tags around variables (e.g. <span style="...">{{ var }}</span>)
            #    Handles <span>, <font>, <b>, <i>, <u> and nested combinations
            for _ in range(3):  # multiple passes for nested wrappers
                template_string = re.sub(
                    r'<(span|font|b|i|u)\b[^>]*>(\s*\{\{.*?\}\}\s*)</\1>',
                    r'\2',
                    template_string,
                    flags=re.DOTALL
                )

            template = Template(template_string)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Errore rendering template: {str(e)}")
            raise

    @staticmethod
    def send_workflow_email(participant, step, landing_url=None, attachments=None, to_override=None):
        """
        Invia email per uno step del workflow

        Args:
            participant: istanza Participant
            step: istanza WorkflowStep
            landing_url: URL landing page (se presente)
            attachments: lista di Attachment model instances (opzionale)

        Returns:
            bool: successo invio
        """
        try:
            # Context per template
            context = {
                'participant': {
                    'name': participant.full_name,
                    'full_name': participant.full_name,
                    'first_name': participant.first_name,
                    'last_name': participant.last_name,
                    'email': participant.email,
                    'phone': participant.phone or '',
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

            # Normalize font: strip all inline font-family from inner tags,
            # then wrap in a div with consistent font so everything matches
            import re
            body_html = re.sub(r'font-family\s*:[^;\"\']+;?\s*', '', body_html)
            body_html = (
                '<div style="font-family: Arial, Helvetica, sans-serif;">'
                + body_html
                + '</div>'
            )

            # Se c'è landing_url ma non è nel template, aggiungilo in fondo
            if landing_url and '{{ landing_url }}' not in (step.body_template or '') and '{{landing_url}}' not in (step.body_template or '') and landing_url not in body_html:
                body_html += (
                    '<div style="text-align:center; margin-top:30px; padding:20px;">'
                    f'<a href="{landing_url}" style="background-color:#795548; color:#fff; '
                    'padding:14px 32px; text-decoration:none; border-radius:8px; '
                    'font-size:16px; font-weight:600; display:inline-block;">'
                    'Accedi alla pagina</a></div>'
                )

            # Renderizza subject
            subject = EmailService.render_template(step.subject, context)

            # Invia
            return EmailService.send_email(
                to_email=to_override or participant.email,
                subject=subject,
                body_html=body_html,
                file_attachments=attachments
            )

        except Exception as e:
            logger.error(f"Errore invio workflow email: {str(e)}")
            return False
