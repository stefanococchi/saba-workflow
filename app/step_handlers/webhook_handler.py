"""Handler per step WEBHOOK — chiamata HTTP POST a URL esterna."""
import logging
from app.step_handlers import register
from app.step_handlers.base import StepHandler

logger = logging.getLogger(__name__)


@register('WEBHOOK')
class WebhookHandler(StepHandler):

    def execute(self, step, practice_result, config, db_session):
        import requests as req

        result = {'type': 'WEBHOOK'}
        url = config.get('webhook_url', '')

        if url:
            try:
                r = req.post(url, json={
                    'practice_id': practice_result.practice_id,
                    'step': step.name,
                    'result_data': practice_result.result_data,
                }, timeout=30)
                result['status_code'] = r.status_code
                result['ok'] = 200 <= r.status_code < 300
                logger.info(f"Webhook step: url={url} status={r.status_code}")
            except Exception as e:
                result['error'] = str(e)
                logger.error(f"Webhook step error: {e}")
        else:
            result['error'] = 'URL webhook mancante'

        return result

    def get_display_data(self, step_config, step_state):
        exec_result = step_state.get('exec_result', {})
        fields = []
        if step_config.get('webhook_url'):
            fields.append({'label': 'URL', 'value': step_config['webhook_url'], 'status': 'ok'})
        if exec_result.get('status_code'):
            ok = 200 <= exec_result['status_code'] < 300
            fields.append({'label': 'Risposta', 'value': str(exec_result['status_code']), 'status': 'ok' if ok else 'error'})
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
