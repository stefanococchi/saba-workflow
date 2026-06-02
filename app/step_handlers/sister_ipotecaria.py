"""Handler per step SISTER_IPOTECARIA — ispezione ipotecaria per soggetto (CF) via AO."""
import base64
import logging
import re
from app.step_handlers import register
from app.step_handlers.base import StepHandler
from app.step_handlers.sister_visura import _extract_pdf, _clean_numeric, FIELD_ALIASES, _find_field

logger = logging.getLogger(__name__)


def _split_cf(val):
    """Splitta codici fiscali multipli separati da ; , o spazio."""
    if not val:
        return []
    parts = [p.strip().upper() for p in re.split(r'[;,|]+', str(val)) if p.strip()]
    # Filtra solo CF validi (16 caratteri alfanumerici)
    return [p for p in parts if re.match(r'^[A-Z0-9]{16}$', p)]


@register('SISTER_IPOTECARIA')
class SisterIpotecariaHandler(StepHandler):

    def execute(self, step, practice_result, config, db_session):
        from app.services import ao_service
        from app.models import PracticeFile

        result = {'type': 'SISTER_IPOTECARIA'}

        # ── 1. Trova sister-agent ──
        sister_agent_id = config.get('sister_agent_id', '')
        if not sister_agent_id:
            agents_list = ao_service.list_agents()
            sa = next((a for a in agents_list if 'sister' in (a.get('name', '') or '').lower()), None)
            if sa:
                sister_agent_id = sa['id']
            else:
                result['error'] = 'Agente sister-agent non trovato'
                return result

        # ── 2. Raccogli dati dagli step precedenti ──
        accumulated = self.get_accumulated_data(practice_result)

        # Appiattisci (stessa logica di sister_visura)
        flat = {}
        for k, v in accumulated.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                for nk, nv in v[0].items():
                    if nk.lower() not in flat and nv:
                        flat[nk.lower()] = nv
            elif isinstance(v, dict):
                for nk, nv in v.items():
                    if nk.lower() not in flat and nv:
                        flat[nk.lower()] = nv
            elif v:
                flat[k.lower()] = v

        result['flat_keys'] = list(flat.keys())
        logger.info(f"Sister ipotecaria flat keys: {list(flat.keys())}")

        # ── 3. Trova codici fiscali ──
        cf_raw = ''
        cf_aliases = ['cf acquirenti', 'codice_fiscale', 'codice fiscale', 'cf', 'codicefiscale',
                       'cf_acquirenti', 'codici_fiscali', 'cf_soggetti']
        for alias in cf_aliases:
            val = flat.get(alias)
            if val:
                cf_raw = str(val)
                break
        # Fallback: cerca chiavi che contengono 'cf' o 'codice_fiscale'
        if not cf_raw:
            for fk, fv in flat.items():
                if ('cf' in fk or 'codice_fiscale' in fk or 'codicefiscale' in fk) and fv:
                    cf_raw = str(fv)
                    break
        # Anche dalla config
        if not cf_raw:
            cf_raw = config.get('codice_fiscale', '')

        codici_fiscali = _split_cf(cf_raw)
        if not codici_fiscali:
            result['error'] = f'Nessun codice fiscale valido trovato. Raw: "{cf_raw[:100]}"'
            return result

        logger.info(f"Sister ipotecaria: {len(codici_fiscali)} CF trovati: {codici_fiscali}")

        # ── 4. Dati comuni ──
        provincia = _find_field(flat, 'provincia', 'provincia', config)
        comune = _find_field(flat, 'comune', 'comune', config).upper()

        base_input = {
            'operation': 'ispezioneIpotecaria',
        }
        if provincia:
            base_input['provincia'] = provincia
        if comune:
            base_input['comune'] = comune

        # Credenziali auth
        if config.get('auth_username'):
            base_input['authProvider'] = config.get('auth_provider', 'sister')
            base_input['authUsername'] = config['auth_username']
            base_input['authPassword'] = config.get('auth_password', '')

        result['input'] = base_input
        result['visure'] = []
        all_ok = True

        # ── 5. Una chiamata SISTER per ogni CF ──
        for cf in codici_fiscali:
            visura_info = {'codiceFiscale': cf}
            sister_input = dict(base_input)
            sister_input['codiceFiscale'] = cf

            logger.info(f"Sister ipotecaria [{cf}] input: {sister_input}")

            try:
                run_result = ao_service.run_agent(sister_agent_id, sister_input)
                task_result = ao_service.poll_task(run_result['taskId'], max_wait=120.0)
                output = task_result.get('output', {})
                status = task_result.get('status', 'unknown')
                visura_info['status'] = status

                if isinstance(output, dict):
                    visura_info['output_keys'] = list(output.keys())

                default_name = f"ipotecaria_{cf}.pdf"
                content, ao_file_name, found_in = _extract_pdf(output)
                file_name = ao_file_name or default_name

                if content:
                    existing = db_session.query(PracticeFile).filter_by(
                        practice_id=practice_result.practice_id, file_name=file_name
                    ).first()
                    if existing:
                        existing.data = content
                        existing.mime_type = 'application/pdf'
                    else:
                        db_session.add(PracticeFile(
                            practice_id=practice_result.practice_id,
                            file_name=file_name,
                            mime_type='application/pdf',
                            data=content,
                        ))
                    db_session.flush()
                    visura_info['file_saved'] = file_name
                    visura_info['file_size'] = len(content)
                    visura_info['file_found_in'] = found_in
                    logger.info(f"Sister ipotecaria [{cf}]: saved {file_name} ({len(content)} bytes)")
                else:
                    visura_info['note'] = 'Nessun file nella risposta'
                    all_ok = False

                if status != 'COMPLETED':
                    all_ok = False
                    visura_info['error'] = task_result.get('error', f'AO status: {status}')

            except Exception as e:
                visura_info['error'] = str(e)
                all_ok = False
                logger.error(f"Sister ipotecaria [{cf}] error: {e}")

            result['visure'].append(visura_info)

        result['status'] = 'COMPLETED' if all_ok else 'FAILED'
        return result

    def get_display_data(self, step_config, step_state):
        exec_result = step_state.get('exec_result', {})
        fields = []

        # Dati comuni
        inp = exec_result.get('input', {})
        if inp.get('provincia'):
            fields.append({'label': 'Provincia', 'value': inp['provincia'], 'status': 'ok'})
        if inp.get('comune'):
            fields.append({'label': 'Comune', 'value': inp['comune'], 'status': 'ok'})

        # Dettaglio per ogni CF
        visure = exec_result.get('visure', [])
        for i, v in enumerate(visure):
            cf = v.get('codiceFiscale', '?')
            prefix = f"CF {i+1}" if len(visure) > 1 else "CF"
            fields.append({'label': prefix, 'value': cf, 'status': 'ok' if v.get('status') == 'COMPLETED' else 'error'})
            if v.get('file_saved'):
                size_kb = (v.get('file_size', 0) / 1024)
                fields.append({'label': f'File {prefix}', 'value': f"{v['file_saved']} ({size_kb:.0f} KB)", 'status': 'ok'})
            elif v.get('status') == 'COMPLETED':
                fields.append({'label': f'File {prefix}', 'value': v.get('note', 'nessun PDF'), 'status': 'error'})
            if v.get('error'):
                fields.append({'label': f'Errore {prefix}', 'value': v['error'], 'status': 'error'})

        # Stato globale
        status = exec_result.get('status')
        if status:
            is_ok = status == 'COMPLETED'
            fields.append({'label': 'Stato', 'value': f"{status} ({len(visure)} ispezioni)", 'status': 'ok' if is_ok else 'error'})

        # Debug su errore
        if exec_result.get('error'):
            fields.append({'label': 'Errore', 'value': exec_result['error'], 'status': 'error'})
        has_error = exec_result.get('status') in ('FAILED', 'TIMEOUT', 'error')
        if has_error:
            flat_keys = exec_result.get('flat_keys', [])
            if flat_keys:
                fields.append({'label': 'Campi trovati', 'value': ', '.join(flat_keys), 'status': 'ok'})

        return {
            'buttons': [
                {'label': 'Salta', 'action': 'skip', 'icon': 'bi-skip-forward', 'variant': 'outline-secondary'},
                {'label': 'Esegui e avanza', 'action': 'complete', 'icon': 'bi-play-fill', 'variant': 'primary'},
            ],
            'auto_execute': True,
            'summary_fields': fields,
        }
