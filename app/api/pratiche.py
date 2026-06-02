"""Blueprint API per Pratiche Documentali (proxy verso Agent Orchestrator)."""
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
from app.services import ao_service
from app import db_session as db
from app.models import PracticeResult, PracticeFile, Participant, WorkflowStep, StepType, ParticipantStatus, ExecutionStatus, Execution
import json
import logging
import re
import threading

logger = logging.getLogger(__name__)

# In-memory job tracking for background processing
_processing_jobs = {}  # practice_id -> {status, progress, total, results, error, started_at}
_stop_flags = {}  # practice_id -> threading.Event (set = stop requested)

pratiche_bp = Blueprint('pratiche', __name__)


@pratiche_bp.route('/agents', methods=['GET'])
def ao_list_agents():
    """Lista agenti AO disponibili."""
    try:
        agents = ao_service.list_agents()
        return jsonify({"agents": agents})
    except Exception as e:
        logger.error(f"AO list agents: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/agent-id', methods=['POST'])
def ao_get_agent_id():
    """Risolve agentId dal nome."""
    try:
        body = request.get_json()
        agent_id = ao_service.get_agent_id_by_name(body["agentName"])
        return jsonify({"agentId": agent_id})
    except Exception as e:
        logger.error(f"AO get agent id: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/catalog/<agent_id>', methods=['GET'])
def ao_get_catalog(agent_id):
    """Ottiene il catalogo documentale di un agent."""
    try:
        result = ao_service.practice_get_catalog(agent_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO get catalog: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/catalog/<agent_id>', methods=['PUT'])
def ao_update_catalog(agent_id):
    """Aggiorna il catalogo documentale di un agent."""
    try:
        body = request.get_json()
        result = ao_service.practice_update_catalog(agent_id, body["catalog"])
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO update catalog: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice/<agent_id>/<practice_id>/info', methods=['GET'])
def ao_practice_info(agent_id, practice_id):
    """Info su una pratica."""
    try:
        result = ao_service.practice_info(agent_id, practice_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO practice info: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice-files/<practice_id>/upload', methods=['POST'])
def ao_practice_upload_files(practice_id):
    """Salva i file nel DB subito, prima dell'elaborazione."""
    try:
        saved = []
        for key in request.files:
            upload = request.files[key]
            content = upload.read()
            filename = upload.filename
            mime = upload.content_type

            existing = db.query(PracticeFile).filter_by(
                practice_id=practice_id, file_name=filename
            ).first()
            if existing:
                existing.data = content
                existing.mime_type = mime
                # Resetta OCR: il contenuto è cambiato, il vecchio OCR non è più valido
                existing.ocr_text = None
                existing.ocr_words = None
                existing.ocr_page_dims = None
            else:
                db.add(PracticeFile(
                    practice_id=practice_id,
                    file_name=filename,
                    mime_type=mime,
                    data=content,
                ))
            db.commit()
            saved.append(filename)
        return jsonify({"saved": saved})
    except Exception as e:
        db.rollback()
        logger.error(f"Upload files: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice-files/<practice_id>/list', methods=['GET'])
def ao_practice_list_files(practice_id):
    """Lista i file salvati nel DB per una pratica."""
    try:
        files = db.query(PracticeFile).filter_by(practice_id=practice_id).all()
        return jsonify({"files": [
            {"file_name": f.file_name, "mime_type": f.mime_type, "has_ocr": bool(f.ocr_text)}
            for f in files
        ]})
    except Exception as e:
        logger.error(f"List practice files: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice-files/<practice_id>/<file_name>/ocr-text', methods=['GET'])
def ao_practice_file_ocr_text(practice_id, file_name):
    """Restituisce il testo OCR estratto da un file."""
    try:
        pf = db.query(PracticeFile).filter_by(practice_id=practice_id, file_name=file_name).first()
        if not pf:
            return jsonify({"error": "File non trovato"}), 404
        return jsonify({"text": pf.ocr_text or "", "has_ocr": bool(pf.ocr_text), "words": pf.ocr_words or [], "page_dims": pf.ocr_page_dims or {}})
    except Exception as e:
        logger.error(f"OCR text read: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice/<agent_id>/<practice_id>/process', methods=['POST'])
def ao_practice_process(agent_id, practice_id):
    """Processa una pratica: carica file e avvia identify+extract."""
    try:
        files = {}
        raw_files = []  # (content, mime, filename) for DB storage
        idx = 0
        for key in request.files:
            upload = request.files[key]
            content = upload.read()
            files[f"file_{idx}"] = (content, upload.content_type, upload.filename)
            raw_files.append((content, upload.content_type, upload.filename))
            idx += 1

        result = ao_service.practice_process(
            agent_id, practice_id, files=files if files else None,
        )

        # Salva file nel DB per il viewer PDF
        for content, mime, filename in raw_files:
            try:
                existing = db.query(PracticeFile).filter_by(
                    practice_id=practice_id, file_name=filename
                ).first()
                if existing:
                    existing.data = content
                    existing.mime_type = mime
                    existing.ocr_text = None
                    existing.ocr_words = None
                    existing.ocr_page_dims = None
                else:
                    db.add(PracticeFile(
                        practice_id=practice_id,
                        file_name=filename,
                        mime_type=mime,
                        data=content,
                    ))
                db.commit()
            except Exception as fe:
                db.rollback()
                logger.warning(f"Salvataggio file DB fallito: {fe}")

        return jsonify(result)
    except Exception as e:
        logger.error(f"AO practice process: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice/<agent_id>/<practice_id>/init-and-process', methods=['POST'])
def ao_practice_init_and_process(agent_id, practice_id):
    """Crea pratica, salva file, assegna workflow e avvia elaborazione — tutto atomicamente."""
    try:
        workflow_id = request.form.get('workflow_id', type=int)

        # ── 1. Crea o trova PracticeResult ──
        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if not pr:
            pr = PracticeResult(
                practice_id=practice_id,
                agent_id=agent_id,
                agent_name=request.form.get('agent_name', ''),
                result_data={'files': {}},
            )
            db.add(pr)
        else:
            pr.agent_id = agent_id

        # ── 2. Salva file nel DB (upsert: se esiste già stesso nome, sovrascrive) ──
        existing_names = {pf.file_name for pf in db.query(PracticeFile).filter_by(practice_id=practice_id).all()}
        saved = []
        for key in request.files:
            upload = request.files[key]
            content = upload.read()
            if not content:
                continue
            if upload.filename in existing_names:
                # Aggiorna file esistente — resetta OCR perché il contenuto potrebbe essere cambiato
                pf = db.query(PracticeFile).filter_by(practice_id=practice_id, file_name=upload.filename).first()
                if pf:
                    pf.data = content
                    pf.mime_type = upload.content_type or 'application/octet-stream'
                    pf.ocr_text = None
                    pf.ocr_words = None
                    pf.ocr_page_dims = None
            else:
                pf = PracticeFile(
                    practice_id=practice_id,
                    file_name=upload.filename,
                    mime_type=upload.content_type or 'application/octet-stream',
                    data=content,
                )
                db.add(pf)
            saved.append(upload.filename)

        # ── 3. Assegna workflow (se specificato) ──
        if workflow_id:
            from app.models import Workflow
            workflow = db.get(Workflow, workflow_id)
            if workflow:
                steps = sorted(workflow.steps, key=lambda s: s.order)
                pr.workflow_id = workflow_id
                pr.current_step_order = 1
                pr.step_states = {str(s.order): {'status': 'pending'} for s in steps}
                if steps:
                    pr.step_states['1']['status'] = 'in_progress'
        elif not pr.workflow_id and agent_id:
            # Auto-bind workflow se nessuno specificato
            _auto_bind_workflow(pr)

        # ── 4. Commit unico — tutto salvato atomicamente ──
        db.commit()
        logger.info(f"Practice {practice_id} initialized: {len(saved)} files, workflow={pr.workflow_id}")

        # ── 5. Avvia elaborazione in background (dopo il commit) ──
        return _start_background_processing(agent_id, practice_id, pr)

    except Exception as e:
        db.rollback()
        logger.error(f"Init and process error: {e}")
        return jsonify({"error": str(e)}), 500


def _start_background_processing(agent_id, practice_id, pr=None):
    """Avvia elaborazione file in background. Usata da init-and-process e process-all."""
    db_files = db.query(PracticeFile).filter_by(practice_id=practice_id).all()
    if not db_files:
        return jsonify({"error": "Nessun file da elaborare"}), 400

    # Controlla se già in corso
    job = _processing_jobs.get(practice_id)
    if job and job['status'] == 'running':
        return jsonify({"ok": True, "already_running": True, "progress": job['progress'], "total": job['total']})

    # Prepara dati file
    files_data = [(pf.file_name, pf.mime_type, bytes(pf.data)) for pf in db_files]

    # Controlla file già elaborati su AO
    already_done = set()
    try:
        info_r = ao_service.practice_info(agent_id, practice_id)
        existing_files = info_r.get('output', {}).get('info', {}).get('files', {})
        for h, ff in existing_files.items():
            if ff.get('state', {}).get('extraction') == 'completed' and ff.get('state', {}).get('identification') == 'completed':
                already_done.add(ff.get('fileName', ''))
    except Exception:
        pass

    to_process = [(fn, mt, data) for fn, mt, data in files_data if fn not in already_done]

    # Salva stato processing nel DB (non in memoria — multi-worker safe)
    _proc_state = {
        'status': 'running',
        'progress': 0,
        'total': len(to_process),
        'skipped': len(files_data) - len(to_process),
        'current_file': '',
        'activity': [],
        'started_at': datetime.utcnow().isoformat(),
    }
    # Anche in memoria per backward compat (stesso worker)
    _processing_jobs[practice_id] = _proc_state

    # Salva nel DB
    pr_for_status = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
    if pr_for_status:
        rd = dict(pr_for_status.result_data or {})
        rd['_processing'] = _proc_state
        pr_for_status.result_data = rd
        from sqlalchemy.orm.attributes import flag_modified as _fm
        _fm(pr_for_status, 'result_data')
        db.commit()

    from flask import current_app
    app = current_app._get_current_object()

    stop_event = threading.Event()
    _stop_flags[practice_id] = stop_event

    def _update_proc_db(bg_db, practice_id, updates):
        """Aggiorna _processing nel DB in modo atomico."""
        bg_pr = bg_db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if bg_pr:
            bg_db.refresh(bg_pr)
            rd = dict(bg_pr.result_data or {})
            proc = rd.get('_processing', {})
            proc.update(updates)
            rd['_processing'] = proc
            bg_pr.result_data = rd
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(bg_pr, 'result_data')
            return bg_pr, rd
        return None, None

    def _bg_process():
        with app.app_context():
            from app import db_session as bg_db
            from sqlalchemy.orm.attributes import flag_modified

            def _log(msg):
                act = {'at': datetime.utcnow().strftime('%H:%M:%S'), 'msg': msg}
                # In memoria (stesso worker)
                job = _processing_jobs.get(practice_id, {})
                if 'activity' in job:
                    job['activity'].append(act)

            try:
                for i, (fn, mt, data) in enumerate(to_process):
                    short_fn = fn[:40] + ('...' if len(fn) > 40 else '')
                    _log(f"📄 Invio file {i+1}/{len(to_process)}: {short_fn}")

                    # Aggiorna progresso in memoria E nel DB
                    job = _processing_jobs.get(practice_id, {})
                    job['current_file'] = fn
                    job['progress'] = i

                    _update_proc_db(bg_db, practice_id, {
                        'current_file': fn, 'progress': i,
                        'activity': job.get('activity', []),
                    })
                    bg_db.commit()

                    if stop_event.is_set():
                        _log("⏹ Elaborazione interrotta dall'utente")
                        _update_proc_db(bg_db, practice_id, {'status': 'stopped'})
                        bg_db.commit()
                        logger.info(f"BG process stopped by user at file {i+1}/{len(to_process)}")
                        break

                    MAX_RETRIES = 3
                    RETRY_DELAYS = [5, 15, 30]
                    last_error = None
                    success = False

                    for attempt in range(MAX_RETRIES):
                        if stop_event.is_set():
                            break
                        try:
                            if attempt > 0:
                                delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
                                _log(f"🔄 Retry {attempt + 1}/{MAX_RETRIES} tra {delay}s...")
                                logger.info(f"BG file {fn}: retry {attempt + 1}/{MAX_RETRIES} tra {delay}s...")
                                import time as _time
                                _time.sleep(delay)

                            # OCR: estrai testo se non già fatto
                            from app.services import ocr_service
                            if not ocr_service.is_configured():
                                _log(f"⚠️ OCR non configurato (PROJECT={bool(os.getenv('GOOGLE_CLOUD_PROJECT'))}, PROC={bool(os.getenv('DOCUMENTAI_PROCESSOR_ID'))}, CREDS={bool(os.getenv('GOOGLE_APPLICATION_CREDENTIALS') or os.getenv('GOOGLE_CREDENTIALS_JSON'))})")
                            if ocr_service.is_configured():
                                pf_ocr = bg_db.query(PracticeFile).filter_by(
                                    practice_id=practice_id, file_name=fn
                                ).first()
                                if pf_ocr and not pf_ocr.ocr_text:
                                    _log(f"🔍 OCR Document AI in corso...")
                                    ocr_result = ocr_service.extract_text(data, mt)
                                    if ocr_result["text"]:
                                        pf_ocr.ocr_text = ocr_result["text"]
                                        pf_ocr.ocr_words = ocr_result.get("words", [])
                                        pf_ocr.ocr_page_dims = ocr_result.get("page_dims", {})
                                        from sqlalchemy.orm.attributes import flag_modified as _fm_ocr
                                        _fm_ocr(pf_ocr, 'ocr_words')
                                        _fm_ocr(pf_ocr, 'ocr_page_dims')
                                        bg_db.commit()
                                        _log(f"📝 OCR: {len(ocr_result['text'])} chars, {len(ocr_result.get('words',[]))} parole, conf={ocr_result['confidence']}")
                                    elif ocr_result["error"]:
                                        _log(f"⚠️ OCR fallito: {ocr_result['error'][:60]}")

                            _log(f"⏳ AO processLocal in corso...")
                            files = {f"file_0": (data, mt, fn)}
                            result = ao_service.practice_process(agent_id, practice_id, files=files)

                            # Controlla se il task AO è fallito o in timeout
                            ao_status = result.get('status', '')
                            if ao_status in ('TIMEOUT', 'FAILED'):
                                raise Exception(f"AO task {ao_status}: {result.get('error', 'unknown')}")

                            output = result.get('output', {})
                            info = output.get('info', output)
                            ao_files = info.get('files', {})

                            for _fh, _fd in ao_files.items():
                                _did = _fd.get('identification', {}).get('documentId', '?')
                                _ao_fn = _fd.get('fileName', '?')
                                _log(f"✅ Identificato: {_did}")
                                logger.info(f"BG file {fn}: AO documentId='{_did}' hash={_fh[:12]} aoFileName='{_ao_fn}'")

                            # Salva file + aggiorna progresso nel DB
                            bg_pr = bg_db.query(PracticeResult).filter_by(practice_id=practice_id).first()
                            if bg_pr:
                                bg_db.refresh(bg_pr)
                                rd = dict(bg_pr.result_data or {})
                                if 'files' not in rd:
                                    rd['files'] = {}
                                for fh, fd in ao_files.items():
                                    if fh in rd['files']:
                                        # Hash già presente: preserva il fileName originale
                                        fd['fileName'] = rd['files'][fh].get('fileName', fd.get('fileName', fn))
                                    else:
                                        # Nuovo hash: imposta il fileName del file appena processato
                                        fd['fileName'] = fn
                                    rd['files'][fh] = fd
                                bg_pr.result_data = rd
                                flag_modified(bg_pr, 'result_data')
                                bg_db.commit()
                                _log(f"💾 Salvato nel DB ({len(rd['files'])} file totali)")
                                logger.info(f"BG file {fn}: AO returned {len(ao_files)}, total in DB={len(rd['files'])}")
                            else:
                                logger.error(f"BG process: PracticeResult not found for {practice_id}")

                            success = True
                            break

                        except Exception as e:
                            last_error = str(e)
                            _log(f"❌ Errore: {str(e)[:80]}")
                            logger.warning(f"BG file {fn}: attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")

                    if not success and not stop_event.is_set():
                        logger.error(f"BG file {fn}: all {MAX_RETRIES} attempts failed: {last_error}")
                        # Salva errore nel DB
                        try:
                            bg_pr, rd = _update_proc_db(bg_db, practice_id, {})
                            if rd:
                                if '_ao_errors' not in rd:
                                    rd['_ao_errors'] = []
                                rd['_ao_errors'].append({'file': fn, 'error': last_error, 'attempts': MAX_RETRIES, 'at': datetime.utcnow().isoformat()})
                                bg_pr.result_data = rd
                                flag_modified(bg_pr, 'result_data')
                                bg_db.commit()
                        except Exception:
                            pass

                # Stato finale nel DB
                final_status = 'stopped' if stop_event.is_set() else 'completed'
                _update_proc_db(bg_db, practice_id, {
                    'status': final_status, 'progress': len(to_process),
                    'activity': _processing_jobs.get(practice_id, {}).get('activity', []),
                })
                bg_db.commit()
                logger.info(f"BG process {final_status} for {practice_id}")

                # Aggiorna anche in memoria
                job = _processing_jobs.get(practice_id, {})
                job['status'] = final_status
                job['progress'] = len(to_process)

            except Exception as e:
                logger.error(f"BG process-all error: {e}")
                try:
                    _update_proc_db(bg_db, practice_id, {'status': 'error', 'error': str(e)})
                    bg_db.commit()
                except Exception:
                    pass
                job = _processing_jobs.get(practice_id, {})
                job['status'] = 'error'
                job['error'] = str(e)
            finally:
                _stop_flags.pop(practice_id, None)

    t = threading.Thread(target=_bg_process, daemon=True)
    t.start()

    return jsonify({
        "ok": True,
        "total": len(to_process),
        "skipped": len(files_data) - len(to_process),
    })


@pratiche_bp.route('/practice/ocr-only/<practice_id>', methods=['POST'])
def ao_practice_ocr_only(practice_id):
    """Esegue solo OCR (Document AI) sui file caricati, senza AO."""
    from app.services import ocr_service
    if not ocr_service.is_configured():
        return jsonify({"error": "OCR (Document AI) non configurato sul server"}), 400

    files = []
    for key in request.files:
        upload = request.files[key]
        content = upload.read()
        if content:
            files.append((upload.filename, upload.content_type or 'application/octet-stream', content))

    if not files:
        return jsonify({"error": "Nessun file caricato"}), 400

    results = []
    for fn, mt, data in files:
        try:
            ocr_result = ocr_service.extract_text(data, mt)
            results.append({
                "file_name": fn,
                "text": ocr_result.get("text", ""),
                "pages": ocr_result.get("pages", 0),
                "confidence": ocr_result.get("confidence"),
                "words_count": len(ocr_result.get("words", [])),
                "error": ocr_result.get("error"),
            })
        except Exception as e:
            logger.error(f"OCR-only error on {fn}: {e}")
            results.append({
                "file_name": fn,
                "text": "",
                "pages": 0,
                "confidence": None,
                "words_count": 0,
                "error": str(e),
            })

    return jsonify({"ok": True, "results": results})


@pratiche_bp.route('/practice/<agent_id>/<practice_id>/process-all', methods=['POST'])
def ao_practice_process_all(agent_id, practice_id):
    """Avvia elaborazione di tutti i file pendenti in background (legacy — usa init-and-process per flusso completo)."""
    try:
        return _start_background_processing(agent_id, practice_id)
    except Exception as e:
        logger.error(f"AO process-all: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice/<practice_id>/process-status', methods=['GET'])
def ao_practice_process_status(practice_id):
    """Polling stato elaborazione — legge da memoria (stesso worker) o DB (altro worker)."""
    # Prima prova in memoria (stesso worker, più veloce)
    job = _processing_jobs.get(practice_id)
    if job:
        return jsonify(job)

    # Fallback: leggi dal DB (altro worker in prod)
    pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
    if pr and pr.result_data and isinstance(pr.result_data, dict):
        proc = pr.result_data.get('_processing')
        if proc and proc.get('status') in ('running', 'completed', 'error', 'stopped'):
            return jsonify(proc)

    return jsonify({"status": "none"})


@pratiche_bp.route('/practice/<practice_id>/process-stop', methods=['POST'])
def ao_practice_process_stop(practice_id):
    """Stop elaborazione in background su richiesta dell'utente."""
    stop_event = _stop_flags.get(practice_id)
    if not stop_event:
        job = _processing_jobs.get(practice_id)
        if not job or job['status'] != 'running':
            return jsonify({"ok": True, "message": "Nessuna elaborazione in corso"})
        return jsonify({"ok": True, "message": "Nessuna elaborazione in corso"})

    stop_event.set()
    logger.info(f"Stop requested for practice {practice_id}")
    return jsonify({"ok": True, "message": "Stop richiesto — l'elaborazione si fermerà dopo il file corrente"})


@pratiche_bp.route('/practice/<agent_id>/<practice_id>/process-stream', methods=['POST'])
def ao_practice_process_stream(agent_id, practice_id):
    """Processa una pratica con streaming SSE evento per evento."""
    try:
        files = {}
        idx = 0
        for key in request.files:
            upload = request.files[key]
            content = upload.read()
            files[f"file_{idx}"] = (content, upload.content_type, upload.filename)
            idx += 1

        # Leggi config AO dentro il contesto Flask PRIMA del generatore
        from flask import current_app
        ao_cfg = {
            'base_url': current_app.config.get('AO_BASE_URL', '').rstrip('/'),
            'token': current_app.config.get('AO_SERVICE_TOKEN', ''),
            'team_id': current_app.config.get('AO_TEAM_ID', ''),
        }

        def generate():
            try:
                import base64
                from pathlib import Path
                import requests as req

                # Prepara binary
                binary = None
                if files:
                    binary = {}
                    for key, (content, mime, filename) in files.items():
                        ext = Path(filename).suffix.lstrip(".")
                        binary[key] = {
                            "data": base64.b64encode(content).decode(),
                            "mimeType": mime,
                            "fileName": filename,
                            "fileExtension": ext,
                        }

                node_item = {"json": {"type": "processLocal", "practiceId": practice_id}}
                if binary:
                    node_item["binary"] = binary
                payload = {
                    "teamId": ao_cfg['team_id'],
                    "stream": True,
                    "input": [node_item],
                }
                headers = {
                    "x-api-key": ao_cfg['token'],
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                }

                r = req.post(
                    f"{ao_cfg['base_url']}/v1/agent/{agent_id}/run",
                    headers=headers,
                    json=payload,
                    timeout=300,
                    stream=True,
                )
                r.raise_for_status()

                for line in r.iter_lines(decode_unicode=True):
                    if line and line.startswith("data: "):
                        try:
                            envelope = json.loads(line[6:])
                            msg = json.loads(envelope["message"]["data"])
                            yield f"data: {json.dumps(msg)}\n\n"
                        except (json.JSONDecodeError, KeyError):
                            continue

                yield "data: {\"__done__\": true}\n\n"
            except Exception as e:
                logger.error(f"AO stream error: {e}")
                yield f"data: {json.dumps({'__error__': str(e)})}\n\n"

        return Response(generate(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    except Exception as e:
        logger.error(f"AO practice process stream: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice/<agent_id>/<practice_id>/save', methods=['POST'])
def ao_practice_save(agent_id, practice_id):
    """Salva modifiche manuali su una pratica."""
    try:
        body = request.get_json()
        result = ao_service.practice_save(
            agent_id, practice_id,
            edited_files=body.get("edited_files"),
            system_facts=body.get("system_facts"),
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO practice save: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice/<agent_id>/<practice_id>/file/<content_hash>', methods=['DELETE'])
def ao_practice_delete_file(agent_id, practice_id, content_hash):
    """Elimina un file da una pratica."""
    try:
        result = ao_service.practice_delete_file(agent_id, practice_id, content_hash)
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO delete file: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice/<agent_id>/<practice_id>/file/<content_hash>/reprocess', methods=['POST'])
def ao_practice_reprocess_file(agent_id, practice_id, content_hash):
    """Rielabora un file di una pratica."""
    try:
        result = ao_service.practice_reprocess_file(agent_id, practice_id, content_hash)
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO reprocess file: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/task/<task_id>/status', methods=['GET'])
def ao_task_status(task_id):
    """Controlla lo stato di un task."""
    try:
        result = ao_service.get_task_status(int(task_id))
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO task status: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/sintesi/generate', methods=['POST'])
def ao_sintesi_generate():
    """Genera sintesi di un documento notarile.
    Accetta OCR text (veloce) oppure file binario come fallback.
    """
    try:
        prompt = request.form.get("prompt", "")
        agent_id = request.form.get("agent_id", "")
        document_type_id = request.form.get("documentTypeId")
        document_type_label = request.form.get("documentTypeLabel")
        model = request.form.get("model", "gemini-2.5-flash")
        ocr_text = request.form.get("ocr_text", "")

        upload = request.files.get("file")
        if not ocr_text and not upload:
            return jsonify({"error": "Testo OCR o file mancante"}), 400

        content = upload.read() if upload else None
        result = ao_service.sintesi_generate(
            agent_id, prompt,
            file_content=content,
            file_mime=upload.content_type if upload else None,
            file_name=upload.filename if upload else None,
            document_type_id=document_type_id,
            document_type_label=document_type_label,
            ocr_text=ocr_text or None,
            model=model,
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO sintesi generate: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/sintesi/pdf', methods=['POST'])
def ao_sintesi_pdf():
    """Genera un PDF elegante dalla sintesi."""
    try:
        body = request.get_json()
        text = body.get("text", "")
        title = body.get("title", "Sintesi documento")
        if not text:
            return jsonify({"error": "Testo mancante"}), 400

        from app.services.pdf_service import generate_sintesi_pdf
        pdf_bytes = generate_sintesi_pdf(title, text)

        return Response(
            pdf_bytes,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="sintesi.pdf"'}
        )
    except Exception as e:
        logger.error(f"Sintesi PDF: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/sintesi/assist', methods=['POST'])
def ao_sintesi_assist():
    """Migliora un prompt per la sintesi."""
    try:
        body = request.get_json()
        result = ao_service.sintesi_assist(
            body["agent_id"],
            draft_prompt=body["draftPrompt"],
            action=body.get("action", "improve"),
            model=body.get("model", "gpt-4o-mini"),
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO sintesi assist: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/askquestions', methods=['POST'])
def ao_ask_questions():
    """Invia una domanda + file della pratica all'agente askquestions."""
    try:
        body = request.get_json() or {}
        question = body.get('question', '').strip()
        practice_id = body.get('practice_id', '')
        agent_id = body.get('agent_id', '')

        if not question:
            return jsonify({"error": "Domanda vuota"}), 400

        # Trova l'agente askquestions se non specificato
        if not agent_id:
            agents = ao_service.list_agents()
            aq = next((a for a in agents if 'askquestion' in (a.get('name', '') or '').lower()), None)
            if aq:
                agent_id = aq['id']
            else:
                return jsonify({"error": "Agente askquestions non trovato"}), 404

        # Raccogli file dalla pratica
        files = {}
        if practice_id:
            db_files = db.query(PracticeFile).filter_by(practice_id=practice_id).all()
            for idx, pf in enumerate(db_files):
                files[f"file_{idx}"] = (bytes(pf.data), pf.mime_type, pf.file_name)

        # Prepara input con la domanda
        import base64
        from pathlib import Path
        binary = None
        if files:
            binary = {}
            for key, (content, mime, filename) in files.items():
                ext = Path(filename).suffix.lstrip(".")
                binary[key] = {
                    "data": base64.b64encode(content).decode(),
                    "mimeType": mime,
                    "fileName": filename,
                    "fileExtension": ext,
                }

        result = ao_service.run_agent(agent_id, {"question": question}, binary=binary)
        # Poll per risultato
        task_result = ao_service.poll_task(result["taskId"], max_wait=120.0)

        # Estrai risposta
        output = task_result.get('output', {})
        answer = output.get('answer', '') or output.get('response', '') or output.get('text', '')
        if not answer and isinstance(output, dict):
            # Prova a trovare la risposta in qualsiasi campo stringa
            for v in output.values():
                if isinstance(v, str) and len(v) > 10:
                    answer = v
                    break
        if not answer:
            answer = json.dumps(output, indent=2, ensure_ascii=False)

        return jsonify({"ok": True, "answer": answer, "raw_output": output})
    except Exception as e:
        logger.error(f"AO ask questions error: {e}")
        return jsonify({"error": str(e)}), 500


# ── Practice Results (persistence in DB) ──────────────────────────

@pratiche_bp.route('/results/<practice_id>', methods=['GET'])
def get_practice_result(practice_id):
    """Carica risultato pratica dal database."""
    try:
        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if not pr:
            return jsonify({"found": False})

        # Verifica fileName: log se ci sono mismatch con i file nel DB
        result_data = pr.result_data or {}
        files = result_data.get('files', {})
        if files:
            db_files = db.query(PracticeFile).filter_by(practice_id=practice_id).all()
            db_file_names = {pf.file_name for pf in db_files}
            for fh, fd in files.items():
                ao_fn = fd.get('fileName', '')
                if ao_fn and ao_fn not in db_file_names:
                    logger.warning(f"Practice {practice_id}: fileName '{ao_fn}' (hash={fh[:12]}) not found in DB. DB files: {db_file_names}")

        return jsonify({"found": True, "data": pr.to_dict()})
    except Exception as e:
        logger.error(f"Get practice result: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/results/<practice_id>', methods=['PUT'])
def save_practice_result(practice_id):
    """Salva/aggiorna risultato pratica nel database."""
    try:
        body = request.get_json()
        is_new = False
        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if pr:
            pr.result_data = body.get('result_data')
            pr.agent_id = body.get('agent_id', pr.agent_id)
            pr.agent_name = body.get('agent_name', pr.agent_name)
        else:
            is_new = True
            pr = PracticeResult(
                practice_id=practice_id,
                agent_id=body.get('agent_id', ''),
                agent_name=body.get('agent_name', ''),
                result_data=body.get('result_data'),
            )
            db.add(pr)

        # Auto-start: se la pratica è nuova e l'agente ha un workflow, assegnalo
        if is_new and not pr.workflow_id and pr.agent_id:
            _auto_bind_workflow(pr)

        db.commit()
        return jsonify({"ok": True, "data": pr.to_dict()})
    except Exception as e:
        db.rollback()
        logger.error(f"Save practice result: {e}")
        return jsonify({"error": str(e)}), 500


def _auto_bind_workflow(practice_result):
    """Se esiste un workflow attivo per l'agente, lo assegna alla pratica e inizializza step 1."""
    from app.models import Workflow, WorkflowStatus
    wf = db.query(Workflow).filter(
        Workflow.ao_agent_id == practice_result.agent_id,
        Workflow.status.in_([WorkflowStatus.ACTIVE, WorkflowStatus.DRAFT]),
    ).first()
    if not wf:
        return

    steps = sorted(wf.steps, key=lambda s: s.order)
    if not steps:
        return

    practice_result.workflow_id = wf.id
    practice_result.current_step_order = 1
    practice_result.step_states = {str(s.order): {'status': 'pending'} for s in steps}
    practice_result.step_states['1']['status'] = 'in_progress'
    logger.info(f"Auto-bound workflow '{wf.name}' to practice {practice_result.practice_id}")


@pratiche_bp.route('/results', methods=['GET'])
def list_practice_results():
    """Lista tutte le pratiche salvate."""
    try:
        results = db.query(PracticeResult).order_by(PracticeResult.updated_at.desc()).all()
        items = []
        for r in results:
            d = r.to_dict()
            # Conteggio file reali dal DB
            d['file_count'] = db.query(PracticeFile).filter_by(
                practice_id=r.practice_id
            ).count()
            items.append(d)
        return jsonify({"results": items})
    except Exception as e:
        logger.error(f"List practice results: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/results/<practice_id>', methods=['DELETE'])
def delete_practice_result(practice_id):
    """Elimina risultato pratica e file associati dal database."""
    try:
        db.query(PracticeFile).filter_by(practice_id=practice_id).delete()
        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if pr:
            db.delete(pr)
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        logger.error(f"Delete practice result: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/files/<practice_id>/<file_name>', methods=['GET'])
def get_practice_file(practice_id, file_name):
    """Serve un file PDF/immagine salvato per una pratica."""
    try:
        pf = db.query(PracticeFile).filter_by(
            practice_id=practice_id, file_name=file_name
        ).first()
        if not pf:
            return jsonify({"error": "File non trovato"}), 404
        return Response(pf.data, mimetype=pf.mime_type,
                        headers={'Content-Disposition': f'inline; filename="{pf.file_name}"'})
    except Exception as e:
        logger.error(f"Get practice file: {e}")
        return jsonify({"error": str(e)}), 500


# ── Document Check Verdict (workflow integration) ────────────────

def _parse_workflow_practice_id(practice_id):
    """Parse practice_id formato WF-{wf_id}-P-{p_id}-S-{s_id}. Returns (wf_id, p_id, s_id) or None."""
    m = re.match(r'^WF-(\d+)-P-(\d+)-S-(\d+)$', practice_id)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


@pratiche_bp.route('/practice/<practice_id>/verdict', methods=['POST'])
def document_check_verdict(practice_id):
    """Valida o rifiuta una pratica document_check, avanzando il workflow."""
    try:
        body = request.get_json() or {}
        action = body.get('action', '')
        notes = body.get('notes', '')

        if action not in ('validate', 'reject'):
            return jsonify({"error": "Azione non valida (validate/reject)"}), 400

        # Parse practice_id per estrarre workflow/participant/step
        parsed = _parse_workflow_practice_id(practice_id)
        if not parsed:
            return jsonify({"error": "Practice non collegata a un workflow", "workflow_linked": False}), 200

        wf_id, participant_id, step_id = parsed

        participant = db.get(Participant, participant_id)
        if not participant:
            return jsonify({"error": "Partecipante non trovato"}), 404

        step = db.get(WorkflowStep, step_id)
        if not step or step.type != StepType.DOCUMENT_CHECK:
            return jsonify({"error": "Step non trovato o tipo errato"}), 404

        # First-responder: controlla se già gestito
        collected = dict(participant.collected_data or {})
        if collected.get('_doc_check_handled'):
            return jsonify({
                "ok": True,
                "already_handled": True,
                "previous_action": collected.get('_doc_check_action'),
            })

        config = step.skip_conditions or {}

        # Segna come gestito
        collected['_doc_check_handled'] = True
        collected['_doc_check_action'] = action
        collected['_doc_check_at'] = datetime.utcnow().isoformat()
        collected['_doc_check_notes'] = notes
        participant.collected_data = collected

        # Aggiorna PracticeResult
        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if pr and pr.result_data:
            rd = dict(pr.result_data)
            rd['validation'] = {
                'outcome': 'OK' if action == 'validate' else 'REJECTED',
                'action': action,
                'notes': notes,
                'at': datetime.utcnow().isoformat(),
            }
            pr.result_data = rd

        # Aggiorna execution
        ex = db.query(Execution).filter(
            Execution.participant_id == participant_id,
            Execution.step_id == step_id,
            Execution.status == ExecutionStatus.SENT,
        ).first()
        if ex:
            ex.status = ExecutionStatus.COMPLETED if action == 'validate' else ExecutionStatus.FAILED
            ex.completed_at = datetime.utcnow()

        # Log activity
        from app.services.activity_service import log_activity
        log_activity(
            workflow_id=wf_id,
            event_type=f'document_check_{action}d',
            description=f'{participant.full_name or participant.email} — pratica {action}d' + (f': {notes}' if notes else ''),
            participant_id=participant_id,
        )

        # Branching — stessa logica di human_approval
        from app.services.scheduler_service import SchedulerService

        if action == 'validate':
            if_validated = config.get('if_validated', 'continue')
            if if_validated == 'complete':
                participant.status = ParticipantStatus.COMPLETED
                participant.completed_at = datetime.utcnow()
                SchedulerService.cancel_scheduled_executions(participant.id)
            elif if_validated == 'jump' and config.get('if_validated_step'):
                target_order = config['if_validated_step']
                target_step = next((s for s in participant.workflow.steps if s.order == target_order), None)
                if target_step:
                    SchedulerService.schedule_step(participant, target_step, delay_hours=0)
            else:
                SchedulerService._schedule_next_step(participant, step)
        else:
            if_rejected = config.get('if_rejected', 'stop')
            if if_rejected == 'continue':
                SchedulerService._schedule_next_step(participant, step)
            elif if_rejected == 'jump' and config.get('if_rejected_step'):
                target_order = config['if_rejected_step']
                target_step = next((s for s in participant.workflow.steps if s.order == target_order), None)
                if target_step:
                    SchedulerService.schedule_step(participant, target_step, delay_hours=0)
            else:
                participant.status = ParticipantStatus.COMPLETED
                participant.completed_at = datetime.utcnow()
                SchedulerService.cancel_scheduled_executions(participant.id)

        db.commit()
        return jsonify({"ok": True, "action": action, "workflow_linked": True})

    except Exception as e:
        db.rollback()
        logger.error(f"Document check verdict error: {e}")
        return jsonify({"error": str(e)}), 500


# ── Backoffice Workflow (pratica-driven) ─────────────────────────

@pratiche_bp.route('/practice/<practice_id>/start-workflow', methods=['POST'])
def start_practice_workflow(practice_id):
    """Associa un workflow a una pratica e inizializza al primo step."""
    try:
        body = request.get_json() or {}
        workflow_id = body.get('workflow_id')
        if not workflow_id:
            return jsonify({"error": "workflow_id richiesto"}), 400

        from app.models import Workflow
        workflow = db.get(Workflow, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow non trovato"}), 404

        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if not pr:
            return jsonify({"error": "Pratica non trovata"}), 404

        steps = sorted(workflow.steps, key=lambda s: s.order)
        if not steps:
            return jsonify({"error": "Workflow senza step"}), 400

        pr.workflow_id = workflow_id
        pr.current_step_order = 1
        pr.step_states = {str(s.order): {'status': 'pending'} for s in steps}
        # Segna il primo step come "in_progress"
        pr.step_states['1']['status'] = 'in_progress'
        db.commit()

        return jsonify({
            "ok": True,
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "current_step_order": 1,
            "total_steps": len(steps),
            "steps": [{'order': s.order, 'name': s.name, 'type': s.type.name} for s in steps],
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Start practice workflow error: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice/<practice_id>/workflow-status', methods=['GET'])
def get_practice_workflow_status(practice_id):
    """Stato corrente del workflow associato a una pratica."""
    try:
        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if not pr or not pr.workflow_id:
            return jsonify({"has_workflow": False})

        from app.models import Workflow
        workflow = db.get(Workflow, pr.workflow_id)
        if not workflow:
            return jsonify({"has_workflow": False})

        steps = sorted(workflow.steps, key=lambda s: s.order)
        step_states = pr.step_states or {}

        # Accumula contesto da tutti gli step completati
        accumulated_data = {}
        # Confronto campi: per ogni campo, raccogli tutti i valori trovati
        comparison_fields = {}  # field_name -> [{ value, doc_type }]
        for s in steps:
            ss = step_states.get(str(s.order), {})
            if ss.get('status') == 'completed' and ss.get('extracted_data'):
                accumulated_data.update(ss['extracted_data'])
                for doc_type, fields in ss['extracted_data'].items():
                    if not isinstance(fields, dict):
                        continue
                    for field_name, field_value in fields.items():
                        if field_value is None or str(field_value).strip() == '':
                            continue
                        if field_name not in comparison_fields:
                            comparison_fields[field_name] = []
                        comparison_fields[field_name].append({
                            'value': field_value,
                            'doc_type': doc_type,
                        })
        # Marca i campi con valori discordanti (normalizzato)
        import re, unicodedata
        def _norm_compare(v):
            """Normalizza un valore per confronto: lowercase, no accenti, no spazi extra."""
            if isinstance(v, (list, dict)):
                v = json.dumps(v, sort_keys=True, ensure_ascii=False)
            s = str(v).strip().lower()
            # Rimuovi accenti (è→e, à→a)
            s = unicodedata.normalize('NFD', s)
            s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
            # Normalizza spazi/punteggiatura multipli
            s = re.sub(r'\s+', ' ', s)
            return s

        for field_name, entries in comparison_fields.items():
            values = set(_norm_compare(e['value']) for e in entries)
            for e in entries:
                e['match'] = len(values) <= 1

        # Genera display_data per ogni step tramite il suo handler
        from app.step_handlers import get_handler
        steps_data = []
        for s in steps:
            ss = step_states.get(str(s.order), {'status': 'pending'})
            handler = get_handler(s.type.name)
            display_data = handler.get_display_data(s.skip_conditions or {}, ss) if handler else {}
            steps_data.append({
                'order': s.order,
                'name': s.name,
                'type': s.type.name,
                'config': s.skip_conditions or {},
                'state': ss,
                'display_data': display_data,
            })

        return jsonify({
            "has_workflow": True,
            "workflow_id": pr.workflow_id,
            "workflow_name": workflow.name,
            "current_step_order": pr.current_step_order,
            "total_steps": len(steps),
            "steps": steps_data,
            "accumulated_data": accumulated_data,
            "comparison_fields": comparison_fields,
        })
    except Exception as e:
        logger.error(f"Get practice workflow status error: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice/<practice_id>/complete-step', methods=['POST'])
def complete_practice_step(practice_id):
    """Completa lo step corrente e avanza al prossimo. Salva tutto atomicamente nel DB."""
    try:
        body = request.get_json() or {}
        action = body.get('action', 'complete')  # complete | skip
        step_result = body.get('result', {})

        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if not pr or not pr.workflow_id:
            return jsonify({"error": "Nessun workflow associato"}), 400

        from app.models import Workflow
        workflow = db.get(Workflow, pr.workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow non trovato"}), 404

        steps = sorted(workflow.steps, key=lambda s: s.order)
        current_order = pr.current_step_order or 1
        current_step = next((s for s in steps if s.order == current_order), None)
        if not current_step:
            return jsonify({"error": "Step corrente non trovato"}), 400

        step_states = dict(pr.step_states or {})
        config = current_step.skip_conditions or {}
        step_doc_types = config.get('doc_types', [])

        # ── 1. Raccogli dati estratti SOLO per i file rilevanti a questo step ──
        extracted_data = {}
        validated_files = []
        if pr.result_data and isinstance(pr.result_data, dict):
            for fhash, fdata in (pr.result_data.get('files', {})).items():
                doc_type = fdata.get('identification', {}).get('documentId', '') or \
                           fdata.get('identification', {}).get('documentTypeId', fhash)

                # Se lo step ha doc_types, filtra per pertinenza (normalizza spazi/underscore)
                if step_doc_types:
                    _norm = lambda s: s.lower().replace('_', '').replace(' ', '')
                    match = any(
                        _norm(t) in _norm(doc_type) or _norm(doc_type) in _norm(t)
                        for t in step_doc_types
                    )
                    if not match:
                        continue

                validated_files.append({
                    'hash': fhash,
                    'fileName': fdata.get('fileName', ''),
                    'documentId': doc_type,
                })
                if fdata.get('extraction', {}).get('data'):
                    extracted_data[doc_type] = fdata['extraction']['data']

        logger.info(f"complete-step {current_order}: extracted_data keys={list(extracted_data.keys())}, validated_files={len(validated_files)}")
        if extracted_data:
            for dt, fields in extracted_data.items():
                logger.info(f"  doc_type={dt}: {list(fields.keys()) if isinstance(fields, dict) else type(fields)}")

        # ── 2. Salva lo step corrente come completato (atomico) ──
        step_type = current_step.type.name
        step_states[str(current_order)] = {
            'status': 'skipped' if action == 'skip' else 'completed',
            'completed_at': datetime.utcnow().isoformat(),
            'result': step_result,
            'extracted_data': extracted_data,
            'validated_files': validated_files,
        }

        # Esegui azioni automatiche dello step corrente (via handler registry)
        from app.step_handlers import get_handler
        exec_result = {}
        current_handler = get_handler(step_type)
        current_config = current_step.skip_conditions or {}
        should_auto = current_handler.should_auto_execute(current_config) if current_handler else False
        if action != 'skip' and current_handler and should_auto:
            exec_result = _execute_backoffice_step(current_step, pr, body)
            step_states[str(current_order)]['exec_result'] = exec_result

        # ── 3. Pulisci validation dalla result_data (è negli step_states ora) ──
        if pr.result_data and isinstance(pr.result_data, dict):
            rd = dict(pr.result_data)
            rd.pop('validation', None)
            pr.result_data = rd

        # ── 4. Avanza al prossimo step ──
        next_step = next((s for s in steps if s.order > current_order), None)
        if next_step:
            pr.current_step_order = next_step.order
            step_states[str(next_step.order)] = {'status': 'in_progress'}

            # Aggiorna step_states nel model PRIMA dell'auto-execute
            # così il prossimo handler vede i dati aggiornati (extracted_data dello step appena completato)
            pr.step_states = step_states

            # Auto-esegui il prossimo step se il suo handler lo prevede
            next_handler = get_handler(next_step.type.name)
            next_config = next_step.skip_conditions or {}
            next_should_auto = next_handler.should_auto_execute(next_config) if next_handler else False
            if next_handler and next_should_auto:
                try:
                    logger.info(f"Auto-execute step {next_step.order} ({next_step.type.name})...")
                    next_exec_result = _execute_backoffice_step(next_step, pr, body)
                    step_states[str(next_step.order)]['status'] = 'completed'
                    step_states[str(next_step.order)]['completed_at'] = datetime.utcnow().isoformat()
                    step_states[str(next_step.order)]['exec_result'] = next_exec_result
                    logger.info(f"Auto-execute step {next_step.order} completed, exec_result status={next_exec_result.get('status', '?')}")

                    # Avanza ancora — catena di auto-execute per step consecutivi
                    after_next = next((s for s in steps if s.order > next_step.order), None)
                    if after_next:
                        pr.current_step_order = after_next.order
                        step_states[str(after_next.order)] = {'status': 'in_progress'}
                        # Se anche il prossimo è auto-execute, eseguilo
                        after_handler = get_handler(after_next.type.name)
                        after_config = after_next.skip_conditions or {}
                        if after_handler and after_handler.should_auto_execute(after_config):
                            try:
                                logger.info(f"Auto-execute chained step {after_next.order} ({after_next.type.name})...")
                                pr.step_states = step_states  # aggiorna prima dell'exec
                                after_exec = _execute_backoffice_step(after_next, pr, body)
                                step_states[str(after_next.order)]['status'] = 'completed'
                                step_states[str(after_next.order)]['completed_at'] = datetime.utcnow().isoformat()
                                step_states[str(after_next.order)]['exec_result'] = after_exec
                                logger.info(f"Auto-execute chained step {after_next.order} completed")
                                # Continua catena
                                final_next = next((s for s in steps if s.order > after_next.order), None)
                                if final_next:
                                    pr.current_step_order = final_next.order
                                    step_states[str(final_next.order)] = {'status': 'in_progress'}
                                else:
                                    pr.current_step_order = None
                            except Exception as e2:
                                logger.error(f"Auto-execute chained step {after_next.order} failed: {e2}")
                                step_states[str(after_next.order)]['status'] = 'error'
                                step_states[str(after_next.order)]['error'] = str(e2)
                    else:
                        pr.current_step_order = None
                except Exception as e:
                    logger.error(f"Auto-execute step {next_step.order} failed: {e}", exc_info=True)
                    step_states[str(next_step.order)]['status'] = 'error'
                    step_states[str(next_step.order)]['error'] = str(e)
        else:
            # Workflow completato
            pr.current_step_order = None

        # ── 5. Salva tutto in un unico commit ──
        pr.step_states = step_states
        db.commit()

        # ── 6. Rispondi con lo stato aggiornato (dal DB, non calcolato) ──
        db.refresh(pr)
        return jsonify({
            "ok": True,
            "completed_step": current_order,
            "workflow_completed": pr.current_step_order is None,
            "current_step_order": pr.current_step_order,
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Complete practice step error: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice/<practice_id>/go-back-step', methods=['POST'])
def go_back_practice_step(practice_id):
    """Torna allo step precedente del workflow, resettandone lo stato."""
    try:
        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if not pr or not pr.workflow_id:
            return jsonify({"error": "Nessun workflow associato"}), 400

        from app.models import Workflow
        workflow = db.get(Workflow, pr.workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow non trovato"}), 404

        steps = sorted(workflow.steps, key=lambda s: s.order)
        current_order = pr.current_step_order

        # Se il workflow è completato (current_step_order=None), torna all'ultimo step
        if current_order is None:
            prev_step = steps[-1] if steps else None
        else:
            prev_step = None
            for s in steps:
                if s.order >= current_order:
                    break
                prev_step = s

        if not prev_step:
            return jsonify({"error": "Sei già al primo step"}), 400

        # Resetta lo step precedente a in_progress e rimuovi lo stato corrente
        step_states = dict(pr.step_states or {})
        step_states[str(prev_step.order)] = {'status': 'in_progress'}
        if current_order is not None:
            step_states.pop(str(current_order), None)

        pr.current_step_order = prev_step.order
        pr.step_states = step_states
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(pr, 'step_states')
        db.commit()
        db.refresh(pr)

        logger.info(f"go-back-step {practice_id}: {current_order} -> {prev_step.order}")
        return jsonify({
            "ok": True,
            "current_step_order": pr.current_step_order,
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Go back practice step error: {e}")
        return jsonify({"error": str(e)}), 500


def _execute_backoffice_step(step, practice_result, body):
    """Esegue uno step automatico tramite il suo handler registrato."""
    from app.step_handlers import get_handler
    config = step.skip_conditions or {}
    handler = get_handler(step.type.name)
    if not handler:
        logger.warning(f"No handler for step type {step.type.name}")
        return {'type': step.type.name, 'error': f'Nessun handler per {step.type.name}'}
    try:
        return handler.execute(step, practice_result, config, db)
    except Exception as e:
        logger.error(f"Execute step {step.type.name} error: {e}")
        return {'type': step.type.name, 'error': str(e)}


@pratiche_bp.route('/test/sister-visura', methods=['POST'])
def test_sister_visura():
    """Test diretto Sister Visura — bypassa workflow e estrazione, usa dati manuali."""
    try:
        body = request.get_json() or {}
        # Dati catastali obbligatori
        sister_input = {
            'operation': body.get('operation', 'visuraStorica'),
            'tipoCatasto': body.get('tipoCatasto', 'F'),
            'tipoVisura': body.get('tipoVisura', 'sintetica'),
            'provincia': body.get('provincia', ''),
            'comune': body.get('comune', ''),
            'foglio': body.get('foglio', ''),
            'particella': body.get('particella', ''),
            'subalterno': body.get('subalterno', ''),
        }
        if body.get('authUsername'):
            sister_input['authProvider'] = body.get('authProvider', 'sister')
            sister_input['authUsername'] = body['authUsername']
            sister_input['authPassword'] = body.get('authPassword', '')

        # Trova sister-agent
        agents_list = ao_service.list_agents()
        sa = next((a for a in agents_list if 'sister' in (a.get('name', '') or '').lower()), None)
        if not sa:
            return jsonify({"error": "Agente sister-agent non trovato"}), 404

        logger.info(f"TEST Sister visura input: {sister_input}")
        run_result = ao_service.run_agent(sa['id'], sister_input)
        task_result = ao_service.poll_task(run_result['taskId'], max_wait=120.0)

        return jsonify({"ok": True, "task_result": task_result})
    except Exception as e:
        logger.error(f"TEST Sister visura error: {e}")
        return jsonify({"error": str(e)}), 500


## _execute_sister_visura rimossa — logica spostata in app/step_handlers/sister_visura.py
