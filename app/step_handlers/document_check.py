"""Handler per step DOCUMENT_CHECK — verifica manuale documenti."""
from app.step_handlers import register
from app.step_handlers.base import StepHandler


@register('DOCUMENT_CHECK')
class DocumentCheckHandler(StepHandler):

    @property
    def is_auto_execute(self):
        return False  # Richiede validazione umana

    def execute(self, step, practice_result, config, db_session):
        return {'type': 'DOCUMENT_CHECK', 'note': 'Validazione manuale'}

    def get_display_data(self, step_config, step_state):
        status = step_state.get('status', 'pending')
        validated = step_state.get('validated_files', [])

        fields = []
        if status == 'completed':
            fields.append({'label': 'File validati', 'value': str(len(validated)), 'status': 'ok'})
            for vf in validated[:5]:
                fields.append({'label': vf.get('documentId', ''), 'value': vf.get('fileName', ''), 'status': 'ok'})

        return {
            'buttons': [
                {'label': 'Rifiuta', 'action': 'reject', 'icon': 'bi-x-lg', 'variant': 'outline-secondary'},
                {'label': 'Valida e avanza', 'action': 'validate', 'icon': 'bi-check-lg', 'variant': 'primary'},
            ],
            'auto_execute': False,
            'summary_fields': fields,
        }
