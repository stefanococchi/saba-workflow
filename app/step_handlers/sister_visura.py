"""Handler per step SISTER_VISURA — visure catastali da portale SISTER via AO.

Supporta valori multipli (es. subalterno "46; 66"): genera una visura
per ogni combinazione F/M/S unica.
"""
import base64
import logging
import re
from app.step_handlers import register
from app.step_handlers.base import StepHandler

logger = logging.getLogger(__name__)

# Alias: nomi alternativi per campi catastali
FIELD_ALIASES = {
    'particella': ['particella', 'mappale', 'numero_particella', 'numero_mappale'],
    'foglio': ['foglio', 'numero_foglio'],
    'subalterno': ['subalterno', 'sub', 'numero_subalterno'],
    'comune': ['comune', 'comune_catastale', 'comune_immobile'],
    'provincia': ['provincia', 'sigla_provincia', 'provincia_immobile'],
}


def _find_field(flat, sister_key, source_key, config):
    """Cerca un campo in flat con alias, match parziale, e fallback config."""
    val = flat.get(source_key.lower())
    if not val:
        for alias in FIELD_ALIASES.get(sister_key, []):
            val = flat.get(alias.lower())
            if val:
                break
    if not val:
        for fk, fv in flat.items():
            if sister_key in fk and fv:
                val = fv
                break
    if not val:
        val = config.get(sister_key, '')
    return str(val).strip() if val else ''


def _split_multi(val):
    """Splitta valori multipli separati da ; , o spazi (es. '46; 66' -> ['46', '66'])."""
    if not val:
        return ['']
    parts = [p.strip() for p in re.split(r'[;,|]+', val) if p.strip()]
    return parts if parts else ['']


def _extract_pdf(output):
    """Cerca e restituisce (content_bytes, file_name, found_in) dall'output AO."""
    file_data = None
    file_name = None
    found_in = None
    content = None

    if not isinstance(output, dict):
        return None, None, None

    # A. Binary output preservato da _extract_useful_output
    binary_out = output.get('_binary')
    if binary_out and isinstance(binary_out, dict):
        for bk, bv in binary_out.items():
            if isinstance(bv, dict) and bv.get('data'):
                content = base64.b64decode(bv['data'])
                file_name = bv.get('fileName')
                found_in = f'_binary.{bk}'
                break
            elif isinstance(bv, str) and len(bv) > 100:
                content = base64.b64decode(bv)
                found_in = f'_binary.{bk}'
                break
    elif binary_out and isinstance(binary_out, list):
        for i, bv in enumerate(binary_out):
            if isinstance(bv, dict) and bv.get('data'):
                content = base64.b64decode(bv['data'])
                file_name = bv.get('fileName')
                found_in = f'_binary[{i}]'
                break

    # B. Chiavi note e sotto-dict
    if not content:
        search_targets = [output]
        for k, v in output.items():
            if isinstance(v, dict) and k != '_binary':
                search_targets.append(v)
        for target in search_targets:
            for key in ('file', 'pdf', 'data', 'document', 'binary', 'content', 'output', 'result', 'visura'):
                if key in target and target[key]:
                    file_data = target[key]
                    found_in = key
                    break
            if file_data:
                break

    # C. Fallback: stringa base64 lunga
    if not content and not file_data:
        for key, val in output.items():
            if key == '_binary':
                continue
            if isinstance(val, str) and len(val) > 500:
                file_data = val
                found_in = key
                break
            if isinstance(val, dict):
                for k2, v2 in val.items():
                    if isinstance(v2, str) and len(v2) > 500:
                        file_data = v2
                        found_in = f'{key}.{k2}'
                        break
                if file_data:
                    break

    if output.get('fileName'):
        file_name = output['fileName']

    # Decodifica
    if not content and file_data:
        if isinstance(file_data, str):
            content = base64.b64decode(file_data)
        elif isinstance(file_data, dict) and file_data.get('data'):
            content = base64.b64decode(file_data['data'])
        elif isinstance(file_data, (bytes, bytearray)):
            content = file_data

    return content, file_name, found_in


@register('SISTER_VISURA')
class SisterVisuraHandler(StepHandler):

    def _flatten_accumulated(self, accumulated):
        """Appiattisci dati estratti in dict flat con chiavi lowercase."""
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

        # Parsa tripletta se presente
        tripletta = flat.get('tripletta')
        if tripletta:
            if isinstance(tripletta, str) and re.search(r'[/\-]', tripletta):
                parts = [p.strip() for p in re.split(r'[/\-]', tripletta)]
                if len(parts) >= 1 and parts[0] and 'foglio' not in flat:
                    flat['foglio'] = parts[0]
                if len(parts) >= 2 and parts[1] and 'particella' not in flat and 'mappale' not in flat:
                    flat['particella'] = parts[1]
                if len(parts) >= 3 and parts[2] and 'subalterno' not in flat:
                    flat['subalterno'] = parts[2]
            elif isinstance(tripletta, dict):
                for tk, tv in tripletta.items():
                    if tv and tk.lower() not in flat:
                        flat[tk.lower()] = str(tv)
            elif isinstance(tripletta, list) and tripletta and isinstance(tripletta[0], dict):
                for tk, tv in tripletta[0].items():
                    if tv and tk.lower() not in flat:
                        flat[tk.lower()] = str(tv)

        return flat

    def _build_combinations(self, flat, config):
        """Genera lista di combinazioni F/M/S da valori eventualmente multipli.
        Accoppia per posizione (zip), NON prodotto cartesiano.
        Es. F='175; 175' M='73; 73' S='46; 66' → [(175,73,46), (175,73,66)]
        """
        foglio_raw = _find_field(flat, 'foglio', 'foglio', config)
        particella_raw = _find_field(flat, 'particella', 'particella', config)
        subalterno_raw = _find_field(flat, 'subalterno', 'subalterno', config)

        fogli = _split_multi(foglio_raw)
        particelle = _split_multi(particella_raw)
        subalterni = _split_multi(subalterno_raw)

        # Zip per posizione: ogni indice è un'unità immobiliare
        max_len = max(len(fogli), len(particelle), len(subalterni))
        combos = []
        seen = set()
        for i in range(max_len):
            f = fogli[i] if i < len(fogli) else fogli[-1] if fogli else ''
            p = particelle[i] if i < len(particelle) else particelle[-1] if particelle else ''
            s = subalterni[i] if i < len(subalterni) else subalterni[-1] if subalterni else ''
            combo = (f, p, s)
            if combo not in seen and (f or p or s):
                seen.add(combo)
                combos.append(combo)

        return combos

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

        # ── 2. Raccogli e appiattisci dati catastali ──
        accumulated = self.get_accumulated_data(practice_result)
        flat = self._flatten_accumulated(accumulated)
        result['flat_keys'] = list(flat.keys())
        logger.info(f"Sister visura flat keys: {list(flat.keys())}")

        # ── 3. Dati comuni (non catastali) ──
        provincia = _find_field(flat, 'provincia', 'provincia', config)
        comune = _find_field(flat, 'comune', 'comune', config).upper()

        base_input = {
            'operation': config.get('operation', 'visuraStorica'),
            'tipoCatasto': config.get('tipo_catasto', 'F'),
            'tipoVisura': config.get('tipo_visura', 'sintetica'),
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

        # ── 4. Genera combinazioni F/M/S ──
        combos = self._build_combinations(flat, config)
        if not combos:
            combos = [('', '', '')]

        result['input'] = base_input
        result['visure'] = []
        all_ok = True

        logger.info(f"Sister visura: {len(combos)} triplette F/M/S -> {len(combos)} chiamate SISTER")

        # ── 5. Una chiamata SISTER per ogni tripletta F/M/S unica ──
        for foglio, particella, subalterno in combos:
            visura_info = {'foglio': foglio, 'particella': particella, 'subalterno': subalterno}
            sister_input = dict(base_input)
            if foglio:
                sister_input['foglio'] = foglio
            if particella:
                sister_input['particella'] = particella
            if subalterno:
                sister_input['subalterno'] = subalterno

            label = f"{foglio}/{particella}/{subalterno}"
            logger.info(f"Sister visura [{label}] input: {sister_input}")

            try:
                run_result = ao_service.run_agent(sister_agent_id, sister_input)
                task_result = ao_service.poll_task(run_result['taskId'], max_wait=120.0)
                output = task_result.get('output', {})
                status = task_result.get('status', 'unknown')
                visura_info['status'] = status

                if isinstance(output, dict):
                    visura_info['output_keys'] = list(output.keys())

                default_name = f"visura_{comune}_{foglio}_{particella}_{subalterno}.pdf"
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
                    logger.info(f"Sister visura [{label}]: saved {file_name} ({len(content)} bytes)")
                else:
                    visura_info['note'] = 'Nessun file nella risposta'
                    if status != 'COMPLETED':
                        all_ok = False

                if status != 'COMPLETED':
                    all_ok = False

            except Exception as e:
                visura_info['error'] = str(e)
                all_ok = False
                logger.error(f"Sister visura [{label}] error: {e}")

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

        # Dettaglio per ogni visura
        visure = exec_result.get('visure', [])
        for i, v in enumerate(visure):
            fms = f"{v.get('foglio', '')}/{v.get('particella', '')}/{v.get('subalterno', '')}"
            prefix = f"Unità {i+1}" if len(visure) > 1 else "F/M/S"
            is_ok = v.get('status') == 'COMPLETED' and v.get('file_saved')
            fields.append({'label': prefix, 'value': fms, 'status': 'ok' if v.get('status') == 'COMPLETED' else 'error'})
            if v.get('file_saved'):
                size_kb = (v.get('file_size', 0) / 1024)
                fields.append({'label': f'File {prefix}', 'value': f"{v['file_saved']} ({size_kb:.0f} KB)", 'status': 'ok'})
            if v.get('error'):
                fields.append({'label': f'Errore {prefix}', 'value': v['error'], 'status': 'error'})

        # Stato globale
        status = exec_result.get('status')
        if status:
            is_ok = status == 'COMPLETED'
            fields.append({'label': 'Stato', 'value': f"{status} ({len(visure)} visure)", 'status': 'ok' if is_ok else 'error'})

        # Debug su errore
        has_error = exec_result.get('status') in ('FAILED', 'TIMEOUT', 'error')
        if has_error:
            flat_keys = exec_result.get('flat_keys', [])
            if flat_keys:
                fields.append({'label': 'Campi trovati', 'value': ', '.join(flat_keys), 'status': 'ok'})
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
