"""Handler per step SISTER_VISURA — visure catastali da portale SISTER via AO."""
import base64
import logging
from app.step_handlers import register
from app.step_handlers.base import StepHandler

logger = logging.getLogger(__name__)


@register('SISTER_VISURA')
class SisterVisuraHandler(StepHandler):

    def execute(self, step, practice_result, config, db_session):
        from app.services import ao_service
        from app.models import PracticeFile

        result = {'type': 'SISTER_VISURA'}

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

        # ── 2. Raccogli dati catastali dagli step precedenti ──
        accumulated = self.get_accumulated_data(practice_result)

        logger.info(f"Sister visura accumulated data keys: {list(accumulated.keys())}")
        if accumulated:
            logger.info(f"Sister visura accumulated sample: { {k: v for k, v in list(accumulated.items())[:10]} }")

        # Appiattisci array di oggetti (es. immobili, acquirenti) in campi di primo livello
        # Prende i valori dal primo elemento dell'array
        flat = {}
        for k, v in accumulated.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                for nested_key, nested_val in v[0].items():
                    if nested_key.lower() not in flat and nested_val:
                        flat[nested_key.lower()] = nested_val
            elif isinstance(v, dict):
                for nested_key, nested_val in v.items():
                    if nested_key.lower() not in flat and nested_val:
                        flat[nested_key.lower()] = nested_val
            elif v:
                flat[k.lower()] = v
        logger.info(f"Sister visura flat keys: {list(flat.keys())}")

        # ── 3. Costruisci input per sister-agent ──
        sister_input = {
            'operation': config.get('operation', 'visuraStorica'),
            'tipoCatasto': config.get('tipo_catasto', 'F'),
            'tipoVisura': config.get('tipo_visura', 'sintetica'),
        }

        # Mapping: campo estratto → campo sister input
        mapping_fields = {
            'provincia': 'provincia',
            'comune': 'comune',
            'foglio': 'foglio',
            'particella': 'particella',
            'subalterno': 'subalterno',
        }
        mapping_fields.update(config.get('field_mapping', {}))

        # Alias: nomi alternativi per lo stesso campo sister
        field_aliases = {
            'particella': ['particella', 'mappale', 'numero_particella', 'numero_mappale'],
            'foglio': ['foglio', 'numero_foglio'],
            'subalterno': ['subalterno', 'sub', 'numero_subalterno'],
            'comune': ['comune', 'comune_catastale'],
            'provincia': ['provincia', 'sigla_provincia'],
        }

        for sister_key, source_key in mapping_fields.items():
            val = flat.get(source_key.lower())
            if not val:
                # Cerca tra gli alias del campo
                for alias in field_aliases.get(sister_key, []):
                    val = flat.get(alias.lower())
                    if val:
                        break
            if not val:
                val = config.get(sister_key, '')
            if val:
                sister_input[sister_key] = str(val)

        # Credenziali auth
        if config.get('auth_username'):
            sister_input['authProvider'] = config.get('auth_provider', 'sister')
            sister_input['authUsername'] = config['auth_username']
            sister_input['authPassword'] = config.get('auth_password', '')

        result['input'] = sister_input
        result['flat_keys'] = list(flat.keys())
        logger.info(f"Sister visura input: {sister_input}")

        # ── 4. Chiama sister-agent ──
        try:
            run_result = ao_service.run_agent(sister_agent_id, sister_input)
            task_result = ao_service.poll_task(run_result['taskId'], max_wait=120.0)
            output = task_result.get('output', {})

            # Salva chiavi output per debug
            if isinstance(output, dict):
                result['output_keys'] = list(output.keys())
                logger.info(f"Sister visura output keys: {list(output.keys())}")
                for ok, ov in output.items():
                    ov_type = type(ov).__name__
                    ov_preview = str(ov)[:120] if not isinstance(ov, (bytes, bytearray)) else f'<binary {len(ov)} bytes>'
                    logger.info(f"  {ok} ({ov_type}): {ov_preview}")
            else:
                result['output_keys'] = [f'<{type(output).__name__}>']
                logger.info(f"Sister visura output type: {type(output).__name__}, preview: {str(output)[:200]}")

            # ── 5. Cerca e salva file PDF ──
            file_data = None
            file_name = f"visura_{sister_input.get('comune', 'visura')}_{sister_input.get('foglio', '')}_{sister_input.get('particella', '')}.pdf"
            content = None

            if isinstance(output, dict):
                # A. Cerca nel binary output preservato da _extract_useful_output
                binary_out = output.get('_binary')
                if binary_out and isinstance(binary_out, dict):
                    # _binary è {key: {data, mimeType, fileName, ...}} o lista
                    for bk, bv in binary_out.items():
                        if isinstance(bv, dict) and bv.get('data'):
                            content = base64.b64decode(bv['data'])
                            file_name = bv.get('fileName', file_name)
                            result['file_found_in'] = f'_binary.{bk}'
                            break
                        elif isinstance(bv, str) and len(bv) > 100:
                            content = base64.b64decode(bv)
                            result['file_found_in'] = f'_binary.{bk}'
                            break
                elif binary_out and isinstance(binary_out, list):
                    for i, bv in enumerate(binary_out):
                        if isinstance(bv, dict) and bv.get('data'):
                            content = base64.b64decode(bv['data'])
                            file_name = bv.get('fileName', file_name)
                            result['file_found_in'] = f'_binary[{i}]'
                            break

                # B. Cerca dentro chiavi note e chiavi nested (es. output.sister.file)
                if not content:
                    search_targets = [output]
                    # Aggiungi sotto-dict come target (es. output['sister'])
                    for k, v in output.items():
                        if isinstance(v, dict) and k != '_binary':
                            search_targets.append(v)

                    for target in search_targets:
                        for key in ('file', 'pdf', 'data', 'document', 'binary', 'content', 'output', 'result', 'visura'):
                            if key in target and target[key]:
                                file_data = target[key]
                                result['file_found_in'] = key
                                break
                        if file_data:
                            break

                # C. Fallback: base64 in qualsiasi valore stringa lungo
                if not content and not file_data:
                    for key, val in output.items():
                        if key == '_binary':
                            continue
                        if isinstance(val, str) and len(val) > 500:
                            file_data = val
                            result['file_found_in'] = key
                            break
                        # Cerca anche dentro sotto-dict
                        if isinstance(val, dict):
                            for k2, v2 in val.items():
                                if isinstance(v2, str) and len(v2) > 500:
                                    file_data = v2
                                    result['file_found_in'] = f'{key}.{k2}'
                                    break
                            if file_data:
                                break

                if output.get('fileName'):
                    file_name = output['fileName']

            # Decodifica file_data se non già decodificato come content
            if not content and file_data:
                if isinstance(file_data, str):
                    content = base64.b64decode(file_data)
                elif isinstance(file_data, dict) and file_data.get('data'):
                    content = base64.b64decode(file_data['data'])
                elif isinstance(file_data, (bytes, bytearray)):
                    content = file_data

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

                result['file_saved'] = file_name
                result['file_size'] = len(content)
                logger.info(f"Sister visura: saved {file_name} ({len(content)} bytes)")
            else:
                result['raw_output'] = str(output)[:500]
                result['note'] = 'Nessun file trovato nella risposta AO'

            result['status'] = task_result.get('status', 'unknown')

        except Exception as e:
            result['error'] = f'Errore chiamata sister-agent: {str(e)}'
            logger.error(f"Sister visura error: {e}")

        return result

    def get_display_data(self, step_config, step_state):
        exec_result = step_state.get('exec_result', {})
        fields = []

        # Input usato
        inp = exec_result.get('input', {})
        if inp.get('provincia'):
            fields.append({'label': 'Provincia', 'value': inp['provincia'], 'status': 'ok'})
        if inp.get('comune'):
            fields.append({'label': 'Comune', 'value': inp['comune'], 'status': 'ok'})
        if inp.get('foglio'):
            fields.append({'label': 'Foglio/Particella/Sub', 'value': f"{inp.get('foglio', '')}/{inp.get('particella', '')}/{inp.get('subalterno', '')}", 'status': 'ok'})

        # Risultato
        if exec_result.get('file_saved'):
            size_kb = (exec_result.get('file_size', 0) / 1024)
            fields.append({'label': 'File', 'value': f"{exec_result['file_saved']} ({size_kb:.0f} KB)", 'status': 'ok'})
        if exec_result.get('error'):
            fields.append({'label': 'Errore', 'value': exec_result['error'], 'status': 'error'})
        if exec_result.get('status'):
            is_ok = exec_result['status'] == 'COMPLETED'
            fields.append({'label': 'Stato AO', 'value': exec_result['status'], 'status': 'ok' if is_ok else 'error'})

        # Output AO: mostra chiavi risposta e dove è stato trovato il file
        output_keys = exec_result.get('output_keys', [])
        if output_keys:
            fields.append({'label': 'Output AO keys', 'value': ', '.join(output_keys), 'status': 'ok'})
        if exec_result.get('file_found_in'):
            fields.append({'label': 'File trovato in', 'value': exec_result['file_found_in'], 'status': 'ok'})
        elif not exec_result.get('file_saved') and exec_result.get('status') == 'COMPLETED':
            fields.append({'label': 'File PDF', 'value': 'non trovato nella risposta AO', 'status': 'error'})

        # Debug extra: mostra input inviato e campi trovati quando fallisce
        has_error = exec_result.get('error') or exec_result.get('status') in ('FAILED', 'TIMEOUT', 'error')
        if has_error:
            flat_keys = exec_result.get('flat_keys', [])
            if flat_keys:
                fields.append({'label': 'Campi trovati', 'value': ', '.join(flat_keys), 'status': 'ok'})
            else:
                fields.append({'label': 'Campi trovati', 'value': 'nessuno', 'status': 'error'})
            input_parts = [f"{k}={v}" for k, v in inp.items() if k not in ('authPassword',)]
            fields.append({'label': 'Input sister', 'value': ' | '.join(input_parts) if input_parts else 'vuoto', 'status': 'ok'})

        return {
            'buttons': [
                {'label': 'Salta', 'action': 'skip', 'icon': 'bi-skip-forward', 'variant': 'outline-secondary'},
                {'label': 'Esegui e avanza', 'action': 'complete', 'icon': 'bi-play-fill', 'variant': 'primary'},
            ],
            'auto_execute': True,
            'summary_fields': fields,
        }
