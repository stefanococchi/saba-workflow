"""Handler per step SISTER_IPOTECARIA — ispezione ipotecaria per soggetto (CF) via AO.

Output AO include:
- PDF ispezione
- Dati strutturati (xmlJson): formalità, soggetti, costo
"""
import base64
import logging
import re
from app.step_handlers import register
from app.step_handlers.base import StepHandler
from app.step_handlers.sister_visura import _extract_pdf, _build_sister_filename, FIELD_ALIASES, _find_field

logger = logging.getLogger(__name__)


def _split_cf(val):
    """Splitta codici fiscali multipli separati da ; , o spazio."""
    if not val:
        return []
    parts = [p.replace(' ', '').strip().upper() for p in re.split(r'[;,|]+', str(val)) if p.strip()]
    return [p for p in parts if re.match(r'^[A-Z0-9]{16}$', p)]


def _extract_sister_data(output):
    """Estrae dati strutturati dalla risposta sister-agent."""
    sister = output.get('sister', {})
    if not isinstance(sister, dict):
        return {}
    result_data = sister.get('result', sister)
    xml_json = result_data.get('xmlJson', sister.get('xmlJson', {}))
    costo = result_data.get('costo', sister.get('costo'))
    return {
        'costo': costo,
        'xmlJson': xml_json,
        'status': sister.get('status'),
        'requestId': sister.get('requestId'),
    }


def _format_formalita(formalita_list):
    """Formatta lista formalità per display nel banner."""
    items = []
    for f in (formalita_list or []):
        desc = f.get('descrizione', '?')
        data = f.get('data', '')
        qualifica = f.get('qualifica', '')
        repertorio = f.get('repertorio', '')
        specie = f.get('specieAtto', '')
        cancellata = ' [CANCELLATA]' if f.get('flagCancellazione') == '1' else ''
        ubicazioni = ', '.join(u.get('descrizione', '') for u in f.get('ubicazioneImmobili', []))
        parts = [desc]
        if data:
            parts.append(data)
        if qualifica:
            parts.append(qualifica)
        if specie:
            parts.append(specie)
        if repertorio:
            parts.append(f'rep. {repertorio}')
        if ubicazioni:
            parts.append(ubicazioni)
        items.append(' — '.join(parts) + cancellata)
    return items


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
        if not cf_raw:
            for fk, fv in flat.items():
                if ('cf' in fk or 'codice_fiscale' in fk or 'codicefiscale' in fk) and fv:
                    cf_raw = str(fv)
                    break
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
        # Rimuovi provincia tra parentesi se presente (es. "CINISELLO BALSAMO (MI)" → "CINISELLO BALSAMO")
        comune = re.sub(r'\s*\([A-Z]{2}\)\s*$', '', comune).strip()

        base_input = {'operation': 'ispezioneIpotecaria'}
        if provincia:
            base_input['provincia'] = provincia
        if comune:
            base_input['comune'] = comune
        if config.get('auth_username'):
            base_input['authProvider'] = config.get('auth_provider', 'sister')
            base_input['authUsername'] = config['auth_username']
            base_input['authPassword'] = config.get('auth_password', '')

        result['input'] = base_input
        result['ispezioni'] = []
        costo_totale = 0.0
        all_ok = True

        # Salva progresso in step_states per polling frontend
        def _save_progress(msg):
            try:
                from sqlalchemy.orm.attributes import flag_modified
                ss = (practice_result.step_states or {})
                ss[str(step.order)] = ss.get(str(step.order), {})
                ss[str(step.order)]['progress'] = msg
                practice_result.step_states = ss
                flag_modified(practice_result, 'step_states')
                db_session.flush()
            except Exception:
                pass

        # ── 5. Una chiamata SISTER per ogni CF ──
        for idx, cf in enumerate(codici_fiscali):
            isp = {'codiceFiscale': cf}
            sister_input = dict(base_input)
            sister_input['codiceFiscale'] = cf

            _save_progress(f"Ipotecaria {idx+1}/{len(codici_fiscali)}: CF {cf} — invio richiesta a SISTER...")
            logger.info(f"Sister ipotecaria [{cf}] input: {sister_input}")

            MAX_RETRIES = 1
            for attempt in range(MAX_RETRIES + 1):
                try:
                    run_result = ao_service.run_agent(sister_agent_id, sister_input)
                    _save_progress(f"Ipotecaria {idx+1}/{len(codici_fiscali)}: CF {cf} — in attesa risposta SISTER...")
                    task_result = ao_service.poll_task(run_result['taskId'], max_wait=60.0)
                    output = task_result.get('output', {})
                    status = task_result.get('status', 'unknown')
                    error_msg = task_result.get('error', '') or ''

                    # Retry su timeout SISTER (max 1 retry)
                    if status != 'COMPLETED' and 'timeout' in error_msg.lower() and attempt < MAX_RETRIES:
                        import time
                        logger.warning(f"Sister ipotecaria [{cf}] timeout (tentativo {attempt + 1}/{MAX_RETRIES + 1}), retry tra 3s...")
                        time.sleep(3)
                        continue

                    isp['status'] = status
                    if attempt > 0:
                        isp['retries'] = attempt

                    # Estrai dati strutturati
                    if isinstance(output, dict):
                        sister_data = _extract_sister_data(output)
                        isp['costo'] = sister_data.get('costo')
                        if isp['costo']:
                            costo_totale += float(isp['costo'])

                        xml_json = sister_data.get('xmlJson', {})
                        isp['formalita'] = xml_json.get('formalita', [])
                        isp['soggetti'] = xml_json.get('soggettiSelezionati', [])
                        isp['documento'] = xml_json.get('documento', {})
                        isp['schema'] = xml_json.get('tipoDocumento', '')
                        isp['num_formalita'] = len(isp['formalita'])

                        logger.info(f"Sister ipotecaria [{cf}]: costo={isp['costo']}, formalità={isp['num_formalita']}")

                    # Salva PDF
                    sogg_cognome = ''
                    for s in isp.get('soggetti', []):
                        if s.get('cognome'):
                            sogg_cognome = re.sub(r'[^A-Za-z]', '', s['cognome']).upper()
                            break
                    file_name = f"ipotecaria_{sogg_cognome}.pdf" if sogg_cognome else f"ipotecaria_{cf}.pdf"
                    content, ao_file_name, found_in = _extract_pdf(output)

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
                        isp['file_saved'] = file_name
                        isp['file_size'] = len(content)
                        logger.info(f"Sister ipotecaria [{cf}]: saved {file_name} ({len(content)} bytes)")

                        # ── Salva subito in result_data con documentId unico ──
                        try:
                            import hashlib
                            from sqlalchemy.orm.attributes import flag_modified
                            db_session.refresh(practice_result)
                            rd = dict(practice_result.result_data or {})
                            if 'files' not in rd:
                                rd['files'] = {}
                            fh_key = hashlib.md5(f"ipotecaria_{cf}".encode()).hexdigest()[:16]
                            doc_id = f"Ipotecaria {cf}"
                            isp_data = {'CODICE_FISCALE': cf}
                            if isp.get('costo'):
                                isp_data['COSTO'] = f"€ {isp['costo']}"
                            if isp.get('num_formalita') is not None:
                                isp_data['FORMALITA'] = f"{isp['num_formalita']} formalità"
                            if isp.get('formalita'):
                                isp_data['ELENCO_FORMALITA'] = [
                                    {'descrizione': f.get('descrizione', '?'),
                                     'data': f.get('data', ''),
                                     'qualifica': f.get('qualifica', ''),
                                     'repertorio': f.get('repertorio', ''),
                                     'specie_atto': f.get('specieAtto', '')}
                                    for f in isp['formalita']
                                ]
                            if isp.get('soggetti'):
                                isp_data['SOGGETTI'] = isp['soggetti']
                            rd['files'][fh_key] = {
                                'fileName': file_name,
                                'identification': {'documentId': doc_id},
                                'state': {'identification': 'completed', 'extraction': 'completed'},
                                'extraction': {'data': isp_data},
                            }
                            practice_result.result_data = rd
                            flag_modified(practice_result, 'result_data')
                            db_session.flush()
                            logger.info(f"Sister ipotecaria [{cf}]: salvato in result_data come '{doc_id}'")
                        except Exception as rd_err:
                            logger.error(f"Sister ipotecaria [{cf}]: errore salvataggio result_data: {rd_err}")
                    else:
                        isp['note'] = 'Nessun file nella risposta'
                        all_ok = False

                    if status != 'COMPLETED':
                        all_ok = False
                        isp['error'] = task_result.get('error', f'AO status: {status}')

                    break  # successo o errore non-timeout, esci dal retry

                except Exception as e:
                    if 'timeout' in str(e).lower() and attempt < MAX_RETRIES:
                        import time
                        logger.warning(f"Sister ipotecaria [{cf}] exception timeout (tentativo {attempt + 1}), retry tra 3s...")
                        time.sleep(3)
                        continue
                    isp['error'] = str(e)
                    all_ok = False
                    logger.error(f"Sister ipotecaria [{cf}] error: {e}")
                    break

            result['ispezioni'].append(isp)

        result['status'] = 'COMPLETED' if all_ok else 'FAILED'
        result['costo_totale'] = costo_totale

        # ── 6. Salva dati strutturati in extracted_data per confronto campi ──
        extracted = {}
        for isp in result['ispezioni']:
            cf = isp.get('codiceFiscale', '?')
            formalita_descs = [f.get('descrizione', '?') for f in isp.get('formalita', [])]
            extracted[f'ipotecaria_{cf}'] = {
                'codice_fiscale': cf,
                'costo': isp.get('costo'),
                'num_formalita': isp.get('num_formalita', 0),
                'formalita': '; '.join(formalita_descs) if formalita_descs else 'nessuna',
                'soggetto': ', '.join(
                    f"{s.get('cognome', '')} {s.get('nome', '')}" for s in isp.get('soggetti', [])
                ),
            }
        result['extracted_data'] = extracted

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

        # Costo totale
        costo = exec_result.get('costo_totale')
        if costo:
            fields.append({'label': 'Costo totale', 'value': f'€ {costo:.2f}', 'status': 'ok'})

        # Dettaglio per ogni CF
        ispezioni = exec_result.get('ispezioni', [])
        for i, isp in enumerate(ispezioni):
            cf = isp.get('codiceFiscale', '?')
            prefix = f"Soggetto {i+1}" if len(ispezioni) > 1 else "Soggetto"
            is_ok = isp.get('status') == 'COMPLETED'

            # CF e soggetto
            sogg_names = ', '.join(
                f"{s.get('cognome', '')} {s.get('nome', '')}" for s in isp.get('soggetti', [])
            )
            cf_label = f"{cf}" + (f" ({sogg_names})" if sogg_names else '')
            fields.append({'label': prefix, 'value': cf_label, 'status': 'ok' if is_ok else 'error'})

            # Costo singolo
            if isp.get('costo'):
                fields.append({'label': f'Costo {prefix}', 'value': f"€ {isp['costo']:.2f}", 'status': 'ok'})

            # Formalità
            num_form = isp.get('num_formalita', 0)
            if num_form > 0:
                formalita_items = _format_formalita(isp.get('formalita', []))
                summary = f"{num_form} formalità"
                fields.append({'label': f'Formalità {prefix}', 'value': summary, 'status': 'ok'})
                # Mostra le prime 5 formalità
                for j, item in enumerate(formalita_items[:5]):
                    fields.append({'label': f'  #{j+1}', 'value': item, 'status': 'ok'})
                if len(formalita_items) > 5:
                    fields.append({'label': '', 'value': f'... e altre {len(formalita_items) - 5}', 'status': 'ok'})
            elif is_ok:
                fields.append({'label': f'Formalità {prefix}', 'value': 'Nessuna formalità trovata', 'status': 'ok'})

            # File
            if isp.get('file_saved'):
                size_kb = (isp.get('file_size', 0) / 1024)
                fields.append({'label': f'File {prefix}', 'value': f"{isp['file_saved']} ({size_kb:.0f} KB)", 'status': 'ok'})
            elif is_ok:
                fields.append({'label': f'File {prefix}', 'value': isp.get('note', 'nessun PDF'), 'status': 'error'})

            if isp.get('error'):
                fields.append({'label': f'Errore {prefix}', 'value': isp['error'], 'status': 'error'})

        # Stato globale
        status = exec_result.get('status')
        if status:
            is_ok = status == 'COMPLETED'
            fields.append({'label': 'Stato', 'value': f"{status} ({len(ispezioni)} ispezioni)", 'status': 'ok' if is_ok else 'error'})

        # Debug su errore
        if exec_result.get('error'):
            fields.append({'label': 'Errore', 'value': exec_result['error'], 'status': 'error'})
        if exec_result.get('status') in ('FAILED', 'TIMEOUT', 'error'):
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
