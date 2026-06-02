"""Handler per step DOCUMENT_CHECK — verifica manuale documenti.

Con config `auto_process: true`, elabora automaticamente i file non ancora
processati tramite AO (identify + extract) prima di fermarsi per validazione.
"""
import logging
from app.step_handlers import register
from app.step_handlers.base import StepHandler

logger = logging.getLogger(__name__)


@register('DOCUMENT_CHECK')
class DocumentCheckHandler(StepHandler):

    @property
    def is_auto_execute(self):
        return False  # Default: richiede validazione umana

    def should_auto_execute(self, config):
        """Se auto_process è attivo, esegue elaborazione AO prima della validazione."""
        return config.get('auto_process', False)

    def execute(self, step, practice_result, config, db_session):
        """Se auto_process, elabora file non processati con AO. Altrimenti no-op."""
        result = {'type': 'DOCUMENT_CHECK'}

        if not config.get('auto_process'):
            result['note'] = 'Validazione manuale'
            return result

        from app.models import PracticeFile
        from app.services import ao_service

        # Trova l'agente AO da usare
        agent_id = config.get('agent_id', '')
        if not agent_id:
            # Cerca il primo agente disponibile
            agents = ao_service.list_agents()
            if agents:
                agent_id = agents[0]['id']
            else:
                result['error'] = 'Nessun agente AO disponibile'
                return result

        # Trova file non ancora elaborati (presenti nel DB ma senza dati in result_data)
        practice_id = practice_result.practice_id
        db_files = db_session.query(PracticeFile).filter_by(practice_id=practice_id).all()

        rd = dict(practice_result.result_data or {})
        if 'files' not in rd:
            rd['files'] = {}
        existing_files = rd['files']

        # Filtra: file che non hanno ancora extraction completata
        # (inclusi file aggiunti da step precedenti come sister_visura)
        to_process = []
        processed_names = set()
        for fh, fd in existing_files.items():
            if fd.get('state', {}).get('extraction') == 'completed':
                processed_names.add(fd.get('fileName', ''))

        for pf in db_files:
            if pf.file_name not in processed_names and pf.data:
                to_process.append(pf)

        logger.info(f"Document_check auto_process: {len(db_files)} file in DB, {len(processed_names)} già elaborati, {len(to_process)} da elaborare")
        for pf in to_process:
            logger.info(f"  -> da elaborare: {pf.file_name} ({len(pf.data)} bytes, {pf.mime_type})")

        processed = []
        errors = []
        for pf in to_process:
            try:
                logger.info(f"Document_check auto_process: elaboro {pf.file_name} con agente {agent_id}")
                files = {
                    "file_0": (pf.data, pf.mime_type or 'application/pdf', pf.file_name)
                }
                ao_result = ao_service.practice_process(agent_id, practice_id, files=files)

                ao_status = ao_result.get('status', '')
                if ao_status in ('TIMEOUT', 'FAILED'):
                    raise Exception(f"AO {ao_status}: {ao_result.get('error', 'unknown')}")

                output = ao_result.get('output', {})
                info = output.get('info', output)
                ao_files = info.get('files', {})

                if not ao_files:
                    logger.warning(f"Document_check auto_process: {pf.file_name} -> nessun file nella risposta AO")
                    errors.append({'file': pf.file_name, 'error': 'Nessun risultato da AO'})
                    continue

                for fh, fd in ao_files.items():
                    fd['fileName'] = pf.file_name
                    rd['files'][fh] = fd
                    doc_type = fd.get('identification', {}).get('documentId', '?')
                    logger.info(f"Document_check auto_process: {pf.file_name} -> {doc_type}")
                    processed.append({'file': pf.file_name, 'doc_type': doc_type})

            except Exception as e:
                logger.error(f"Document_check auto_process error for {pf.file_name}: {e}")
                errors.append({'file': pf.file_name, 'error': str(e)})

        # Salva risultati nel DB
        practice_result.result_data = rd
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(practice_result, 'result_data')
        db_session.flush()

        result['processed'] = processed
        result['errors'] = errors
        result['note'] = f'{len(processed)} file elaborati, {len(errors)} errori'
        return result

    def get_display_data(self, step_config, step_state):
        status = step_state.get('status', 'pending')
        exec_result = step_state.get('exec_result', {})
        validated = step_state.get('validated_files', [])

        fields = []

        # Mostra risultati auto_process se presenti
        if exec_result.get('processed'):
            for p in exec_result['processed']:
                fields.append({'label': p.get('doc_type', 'file'), 'value': p['file'], 'status': 'ok'})
        if exec_result.get('errors'):
            for e in exec_result['errors']:
                fields.append({'label': e['file'], 'value': e['error'], 'status': 'error'})

        if status == 'completed' and validated:
            fields.append({'label': 'File validati', 'value': str(len(validated)), 'status': 'ok'})
            for vf in validated[:5]:
                fields.append({'label': vf.get('documentId', ''), 'value': vf.get('fileName', ''), 'status': 'ok'})

        is_auto = step_config.get('auto_process', False)
        return {
            'buttons': [
                {'label': 'Rifiuta', 'action': 'reject', 'icon': 'bi-x-lg', 'variant': 'outline-secondary'},
                {'label': 'Valida e avanza', 'action': 'validate', 'icon': 'bi-check-lg', 'variant': 'primary'},
            ],
            'auto_execute': is_auto,
            'summary_fields': fields,
        }
