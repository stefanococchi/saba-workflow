"""Handler per step WHATSAPP — invio messaggi WhatsApp."""
from app.step_handlers import register
from app.step_handlers.base import StepHandler


@register('WHATSAPP')
class WhatsAppHandler(StepHandler):

    def execute(self, step, practice_result, config, db_session):
        # TODO: implementare invio WhatsApp per workflow pratica
        return {'type': 'WHATSAPP', 'note': 'WhatsApp non ancora implementato per workflow pratica'}

    def get_display_data(self, step_config, step_state):
        return {
            'buttons': [
                {'label': 'Salta', 'action': 'skip', 'icon': 'bi-skip-forward', 'variant': 'outline-secondary'},
                {'label': 'Esegui e avanza', 'action': 'complete', 'icon': 'bi-play-fill', 'variant': 'primary'},
            ],
            'auto_execute': True,
            'summary_fields': [{'label': 'Stato', 'value': 'Non implementato', 'status': 'pending'}],
        }
