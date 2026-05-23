"""Handler per step EMAIL — invio email automatico."""
import logging
from app.step_handlers import register
from app.step_handlers.base import StepHandler

logger = logging.getLogger(__name__)


@register('EMAIL')
class EmailHandler(StepHandler):

    def execute(self, step, practice_result, config, db_session):
        from app.services.email_service import EmailService

        result = {'type': 'EMAIL'}
        to_email = config.get('custom_to', '')
        subject = config.get('subject', step.subject or '')
        body_html = step.body_template or ''

        if to_email and subject:
            ok = EmailService.send_email(to_email=to_email, subject=subject, body_html=body_html)
            result['sent'] = ok
            result['to'] = to_email
            logger.info(f"Email step: sent={ok} to={to_email}")
        else:
            result['error'] = 'Email o subject mancante'

        return result

    def get_display_data(self, step_config, step_state):
        exec_result = step_state.get('exec_result', {})
        fields = []
        if exec_result.get('to'):
            fields.append({'label': 'Destinatario', 'value': exec_result['to'], 'status': 'ok'})
        if exec_result.get('sent') is not None:
            fields.append({
                'label': 'Stato',
                'value': 'Inviata' if exec_result['sent'] else 'Errore invio',
                'status': 'ok' if exec_result['sent'] else 'error',
            })
        if exec_result.get('error'):
            fields.append({'label': 'Errore', 'value': exec_result['error'], 'status': 'error'})

        return {
            'buttons': [
                {'label': 'Salta', 'action': 'skip', 'icon': 'bi-skip-forward', 'variant': 'outline-secondary'},
                {'label': 'Esegui e avanza', 'action': 'complete', 'icon': 'bi-play-fill', 'variant': 'primary'},
            ],
            'auto_execute': True,
            'summary_fields': fields,
        }
