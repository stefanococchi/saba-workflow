"""Blueprint API per Pratiche Documentali (proxy verso Agent Orchestrator)."""
from datetime import datetime
from io import BytesIO
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


@pratiche_bp.route('/practice-files/<practice_id>/<file_name>/parse-ipotecaria', methods=['GET'])
def ao_parse_ipotecaria(practice_id, file_name):
    """Parsa un PDF ipotecaria SISTER e restituisce dati strutturati."""
    try:
        from app.services.ipotecaria_parser import parse_ipotecaria_pdf
        pf = db.query(PracticeFile).filter_by(practice_id=practice_id, file_name=file_name).first()
        if not pf or not pf.data:
            return jsonify({"error": "File non trovato"}), 404
        data = parse_ipotecaria_pdf(pf.data)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        logger.error(f"Parse ipotecaria error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/practice-files/<practice_id>/zip', methods=['GET'])
def ao_practice_files_zip(practice_id):
    """Scarica tutti i PDF della pratica come ZIP."""
    import zipfile
    try:
        files = db.query(PracticeFile).filter_by(practice_id=practice_id).all()
        if not files:
            return jsonify({"error": "Nessun file trovato"}), 404

        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                if f.data:
                    zf.writestr(f.file_name, f.data)
        buf.seek(0)

        return Response(
            buf.getvalue(),
            mimetype='application/zip',
            headers={'Content-Disposition': f'attachment; filename="documenti_{practice_id}.zip"'}
        )
    except Exception as e:
        logger.error(f"ZIP practice files: {e}")
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
                            # run + poll separati per poter interrompere il poll
                            import base64 as _b64
                            from pathlib import Path as _Path
                            _ext = _Path(fn).suffix.lstrip(".")
                            _binary = {"file_0": {
                                "data": _b64.b64encode(data).decode(),
                                "mimeType": mt, "fileName": fn, "fileExtension": _ext,
                            }}
                            _run = ao_service.run_agent(
                                agent_id,
                                {"type": "processLocal", "practiceId": practice_id},
                                binary=_binary,
                            )
                            _task_id = _run.get('taskId', '')
                            # Traccia taskId corrente nel job (per cancel dall'esterno)
                            job = _processing_jobs.get(practice_id, {})
                            job['current_ao_task_id'] = _task_id
                            result = ao_service.poll_task(_task_id, max_wait=180.0, stop_event=stop_event)
                            job.pop('current_ao_task_id', None)

                            # Controlla se il task AO è fallito, in timeout o cancellato
                            ao_status = result.get('status', '')
                            if ao_status == 'CANCELLED':
                                _log("⏹ Task AO interrotto dall'utente")
                                break
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

    # Tenta di cancellare il task AO corrente (se in polling)
    ao_cancelled = False
    job = _processing_jobs.get(practice_id, {})
    current_task = job.get('current_ao_task_id')
    if current_task:
        try:
            ao_cancelled = ao_service.cancel_task(current_task)
            logger.info(f"AO task {current_task} cancel: {'ok' if ao_cancelled else 'failed/unsupported'}")
        except Exception as e:
            logger.warning(f"AO task cancel error: {e}")

    return jsonify({"ok": True, "ao_cancelled": ao_cancelled,
                     "message": "Stop richiesto — il task AO verrà interrotto"})


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


@pratiche_bp.route('/results/<practice_id>/rename', methods=['PUT'])
def rename_practice(practice_id):
    """Rinomina una pratica (campo name)."""
    try:
        data = request.get_json(force=True)
        new_name = (data.get('name') or '').strip()
        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if not pr:
            return jsonify({"error": "Pratica non trovata"}), 404
        pr.name = new_name or None
        db.commit()
        return jsonify({"ok": True, "name": pr.name})
    except Exception as e:
        db.rollback()
        logger.error(f"Rename practice: {e}")
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
        # I nomi campo vengono normalizzati (lowercase) per unire FOGLIO/foglio
        import re, unicodedata
        def _norm_compare(v):
            """Normalizza un valore per confronto: lowercase, no accenti, no spazi extra."""
            if isinstance(v, (list, dict)):
                v = json.dumps(v, sort_keys=True, ensure_ascii=False)
            s = str(v).strip().lower()
            s = unicodedata.normalize('NFD', s)
            s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
            s = re.sub(r'\s+', ' ', s)
            return s

        comparison_fields = {}  # field_key -> [{ value, doc_type }]
        seen_doc_types = set()
        # Raccogli doc_type da tutti gli step, preferendo i primi (SISTER > document_processing)
        for s in steps:
            ss = step_states.get(str(s.order), {})
            if ss.get('status') not in ('completed', 'in_progress'):
                continue
            # Skip verifica_report — non ha dati da confrontare
            er = ss.get('exec_result', {})
            er_type = er.get('type', '')
            if er_type == 'VERIFICA_REPORT':
                continue
            # Merge extracted_data dallo step + quelli propri dell'handler (exec_result)
            step_extracted = dict(ss.get('extracted_data') or {})
            handler_extracted = er.get('extracted_data', {})
            if handler_extracted and isinstance(handler_extracted, dict):
                step_extracted.update(handler_extracted)
            if not step_extracted:
                continue
            # Visure/ipotecaria: solo dallo step SISTER originale, non da altri step
            is_sister = er_type in ('SISTER_VISURA', 'SISTER_IPOTECARIA')
            accumulated_data.update(step_extracted)
            for doc_type, fields in step_extracted.items():
                dl = doc_type.lower()
                # Skip visure/ipotecaria duplicate se non provengono dallo step SISTER
                if not is_sister and (dl.startswith('visura_') or dl.startswith('visura ')):
                    continue
                # Evita duplicati: normalizza il doc_type e salta se già visto
                dt_norm = re.sub(r'[\s_]+', '_', dl.strip())
                if dt_norm in seen_doc_types:
                    continue
                seen_doc_types.add(dt_norm)
                if not isinstance(fields, dict):
                    continue
                for field_name, field_value in fields.items():
                    if field_value is None or str(field_value).strip() == '':
                        continue
                    field_key = field_name.lower().replace(' ', '_')
                    # Alias: campi con nomi diversi che rappresentano lo stesso dato
                    _FIELD_ALIASES = {
                        'mappale': 'particella',
                        'intestati': 'acquirenti',
                        'parti_acquirenti': 'acquirenti',
                    }
                    field_key = _FIELD_ALIASES.get(field_key, field_key)
                    if field_key not in comparison_fields:
                        comparison_fields[field_key] = []
                    comparison_fields[field_key].append({
                        'value': field_value,
                        'doc_type': doc_type,
                    })

        # ── Arricchisci da result_data.files (include dati iniettati dal parser visura) ──
        files_data = (pr.result_data or {}).get('files', {})
        for fhash, fdata in files_data.items():
            doc_id = (fdata.get('identification', {}).get('documentId', '') or '').strip()
            if not doc_id:
                continue
            dt_norm = re.sub(r'[\s_]+', '_', doc_id.lower().strip())
            if dt_norm in seen_doc_types:
                # doc_type già noto dallo step → integra solo campi mancanti
                pass
            ext_data = fdata.get('extraction', {}).get('data', {})
            if not ext_data or not isinstance(ext_data, dict):
                continue
            for field_name, field_value in ext_data.items():
                if field_value is None or str(field_value).strip() == '':
                    continue
                field_key = field_name.lower().replace(' ', '_')
                _FIELD_ALIASES = {
                    'mappale': 'particella',
                    'intestati': 'acquirenti',
                    'parti_acquirenti': 'acquirenti',
                    'intestatario': 'acquirenti',
                    'codice_fiscale_intestatario': 'cf_acquirenti',
                }
                field_key = _FIELD_ALIASES.get(field_key, field_key)
                # Controlla se questo doc_type ha già un valore per questo campo
                existing = comparison_fields.get(field_key, [])
                already_has = any(e['doc_type'] == doc_id for e in existing)
                if not already_has:
                    if field_key not in comparison_fields:
                        comparison_fields[field_key] = []
                    comparison_fields[field_key].append({
                        'value': field_value,
                        'doc_type': doc_id,
                    })

        # Confronto: il titolo di provenienza è il riferimento.
        # I valori delle visure/altri documenti vengono confrontati contro il titolo.
        # Se il titolo ha valori multipli separati da ";" (es. subalterno "13; 61"),
        # ciascun valore individuale è valido per il match.
        # Se il titolo non ha un valore per un campo, niente discordanza.
        def _is_titolo(doc_type):
            """Identifica doc_type del titolo di provenienza (non visura/ipotecaria)."""
            dt = doc_type.lower()
            return not dt.startswith('visura_') and not dt.startswith('ipotecaria_')

        for field_key, entries in comparison_fields.items():
            titolo_entries = [e for e in entries if _is_titolo(e['doc_type'])]
            other_entries = [e for e in entries if not _is_titolo(e['doc_type'])]

            if not titolo_entries or not other_entries:
                # Nessun confronto possibile (campo solo nel titolo o solo nelle visure)
                for e in entries:
                    e['match'] = True
                continue

            # Raccogli tutti i valori di riferimento dal titolo, splittando per ";"
            ref_values = set()
            for te in titolo_entries:
                for part in str(te['value']).split(';'):
                    normed = _norm_compare(part.strip())
                    if normed:
                        ref_values.add(normed)

            # Il titolo è sempre "corretto"
            for te in titolo_entries:
                te['match'] = True

            # Confronta ciascun altro documento contro i valori del titolo
            for e in other_entries:
                e['match'] = _norm_compare(e['value']) in ref_values

        # Genera display_data per ogni step tramite il suo handler
        from app.step_handlers import get_handler
        steps_data = []
        for s in steps:
            ss = step_states.get(str(s.order), {'status': 'pending'})
            handler = get_handler(s.type.name)
            # Per verifica_report: rigenera le verifiche al volo (così fix al codice
            # si applicano anche alle pratiche già processate)
            if s.type.name == 'VERIFICA_REPORT' and ss.get('exec_result'):
                try:
                    fresh = handler.execute(s, pr, s.skip_conditions or {}, db)
                    ss = dict(ss)
                    ss['exec_result'] = fresh
                except Exception as e:
                    logger.warning(f"Regen verifica_report failed: {e}")
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


@pratiche_bp.route('/practice/<practice_id>/verifica-override', methods=['POST'])
def verifica_override(practice_id):
    """Salva override manuale su un check della verifica report."""
    try:
        body = request.get_json() or {}
        check_id = body.get('check_id')
        new_esito = body.get('esito')  # 'ok', 'warning', 'error'
        nota = body.get('nota', '')

        if not check_id or new_esito not in ('ok', 'warning', 'error'):
            return jsonify({"error": "check_id e esito (ok/warning/error) richiesti"}), 400

        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if not pr:
            return jsonify({"error": "Pratica non trovata"}), 404

        # Trova lo step verifica_report corrente
        step_states = pr.step_states or {}
        vr_order = None
        for order, ss in step_states.items():
            er = ss.get('exec_result', {})
            if er.get('type') == 'VERIFICA_REPORT':
                vr_order = order
                break

        if not vr_order:
            return jsonify({"error": "Nessuno step verifica_report trovato"}), 404

        ss = step_states[vr_order]
        overrides = ss.get('overrides', {})
        overrides[check_id] = {
            'esito': new_esito,
            'nota': nota,
            'timestamp': datetime.utcnow().isoformat(),
        }
        ss['overrides'] = overrides

        # Ricalcola stats con override
        verifiche = ss.get('exec_result', {}).get('verifiche', [])
        total = len(verifiche)
        ok_n = 0
        err_n = 0
        warn_n = 0
        for v in verifiche:
            cid = v.get('check_id', '')
            esito = overrides[cid]['esito'] if cid in overrides else v['esito']
            if esito == 'ok':
                ok_n += 1
            elif esito == 'error':
                err_n += 1
            elif esito == 'warning':
                warn_n += 1
        ss['exec_result']['stats'] = {
            'total': total, 'ok': ok_n, 'errors': err_n, 'warnings': warn_n,
        }

        from sqlalchemy.orm.attributes import flag_modified
        pr.step_states = step_states
        flag_modified(pr, 'step_states')
        db.commit()

        return jsonify({
            "ok": True,
            "check_id": check_id,
            "esito": new_esito,
            "stats": ss['exec_result']['stats'],
            "overrides": overrides,
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Verifica override error: {e}")
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
        # Preserva exec_result e overrides da auto-execute precedente
        step_type = current_step.type.name
        existing_ss = step_states.get(str(current_order), {})
        step_states[str(current_order)] = {
            'status': 'skipped' if action == 'skip' else 'completed',
            'completed_at': datetime.utcnow().isoformat(),
            'result': step_result,
            'extracted_data': extracted_data,
            'validated_files': validated_files,
        }
        # Ripristina exec_result e overrides se lo step era già stato eseguito
        if existing_ss.get('exec_result'):
            step_states[str(current_order)]['exec_result'] = existing_ss['exec_result']
        if existing_ss.get('overrides'):
            step_states[str(current_order)]['overrides'] = existing_ss['overrides']

        # Esegui azioni automatiche dello step corrente (via handler registry)
        from app.step_handlers import get_handler
        exec_result = {}
        current_handler = get_handler(step_type)
        current_config = current_step.skip_conditions or {}
        should_auto = current_handler.should_auto_execute(current_config) if current_handler else False
        if action != 'skip' and current_handler and should_auto:
            exec_result = _execute_backoffice_step(current_step, pr, body)
            step_states[str(current_order)]['exec_result'] = exec_result
            # Ri-raccogli extracted_data DOPO l'handler (potrebbe aver salvato nuovi file)
            db.refresh(pr)
            if pr.result_data and isinstance(pr.result_data, dict):
                for fhash, fdata in pr.result_data.get('files', {}).items():
                    doc_type = fdata.get('identification', {}).get('documentId', '') or \
                               fdata.get('identification', {}).get('documentTypeId', fhash)
                    if step_doc_types:
                        _norm = lambda s: s.lower().replace('_', '').replace(' ', '')
                        if not any(_norm(t) in _norm(doc_type) or _norm(doc_type) in _norm(t) for t in step_doc_types):
                            continue
                    if fdata.get('extraction', {}).get('data'):
                        extracted_data[doc_type] = fdata['extraction']['data']
            # Merge extracted_data dall'handler (es. ipotecaria_CF)
            if isinstance(exec_result, dict) and exec_result.get('extracted_data'):
                extracted_data.update(exec_result['extracted_data'])
            step_states[str(current_order)]['extracted_data'] = extracted_data

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

            # Helper: raccogli extracted_data e validated_files per uno step auto-eseguito
            def _collect_step_data(step_obj, step_config):
                """Dopo auto-execute, raccogli extracted_data dai file in result_data."""
                step_doc_types = step_config.get('doc_types', [])
                ext_data = {}
                val_files = []
                # Rileggi result_data (potrebbe essere stato aggiornato dall'handler)
                db.refresh(pr)
                rd = pr.result_data if isinstance(pr.result_data, dict) else {}
                for fhash, fdata in rd.get('files', {}).items():
                    doc_type = fdata.get('identification', {}).get('documentId', '') or \
                               fdata.get('identification', {}).get('documentTypeId', fhash)
                    if step_doc_types:
                        _norm = lambda s: s.lower().replace('_', '').replace(' ', '')
                        if not any(_norm(t) in _norm(doc_type) or _norm(doc_type) in _norm(t) for t in step_doc_types):
                            continue
                    val_files.append({'hash': fhash, 'fileName': fdata.get('fileName', ''), 'documentId': doc_type})
                    if fdata.get('extraction', {}).get('data'):
                        ext_data[doc_type] = fdata['extraction']['data']
                return ext_data, val_files

            # Auto-esegui step successivi in catena
            remaining = [s for s in steps if s.order > next_step.order]
            auto_chain = [next_step]  # parti dal prossimo

            for chain_step in auto_chain:
                chain_handler = get_handler(chain_step.type.name)
                chain_config = chain_step.skip_conditions or {}
                chain_should_auto = chain_handler.should_auto_execute(chain_config) if chain_handler else False

                if not chain_handler or not chain_should_auto:
                    break

                try:
                    logger.info(f"Auto-execute step {chain_step.order} ({chain_step.type.name})...")
                    pr.step_states = step_states  # aggiorna prima dell'exec
                    chain_exec = _execute_backoffice_step(chain_step, pr, body)
                    # Raccogli extracted_data per il confronto campi
                    ext_data, val_files = _collect_step_data(chain_step, chain_config)
                    # Merge: se l'handler restituisce extracted_data propri (es. ipotecaria)
                    if isinstance(chain_exec, dict) and chain_exec.get('extracted_data'):
                        ext_data.update(chain_exec['extracted_data'])
                    step_states[str(chain_step.order)]['status'] = 'completed'
                    step_states[str(chain_step.order)]['completed_at'] = datetime.utcnow().isoformat()
                    step_states[str(chain_step.order)]['exec_result'] = chain_exec
                    step_states[str(chain_step.order)]['extracted_data'] = ext_data
                    step_states[str(chain_step.order)]['validated_files'] = val_files
                    logger.info(f"Auto-execute step {chain_step.order} completed, extracted={list(ext_data.keys())}, files={len(val_files)}")

                    # Avanza al prossimo
                    next_in_chain = next((s for s in steps if s.order > chain_step.order), None)
                    if next_in_chain:
                        pr.current_step_order = next_in_chain.order
                        step_states[str(next_in_chain.order)] = {'status': 'in_progress'}
                        # Dopo uno step SISTER: ferma la catena per mostrare i risultati.
                        # Il frontend auto-triggerà il prossimo step.
                        # Verifica report: esegui calcolo ma resta in_progress per review manuale.
                        if chain_step.type.name == 'VERIFICA_REPORT':
                            # Verifica report resta lo step corrente per review manuale
                            pr.current_step_order = chain_step.order
                            step_states[str(chain_step.order)]['status'] = 'in_progress'
                            if 'completed_at' in step_states[str(chain_step.order)]:
                                del step_states[str(chain_step.order)]['completed_at']
                            # Annulla l'avanzamento al prossimo step
                            step_states.pop(str(next_in_chain.order), None)
                            logger.info(f"Auto-chain: verifica_report step {chain_step.order} in attesa di review")
                        elif chain_step.type.name in ('SISTER_VISURA', 'SISTER_IPOTECARIA'):
                            logger.info(f"Auto-chain: pausa dopo {chain_step.type.name} step {chain_step.order}")
                        else:
                            auto_chain.append(next_in_chain)  # continua catena
                    else:
                        pr.current_step_order = None
                except Exception as e:
                    logger.error(f"Auto-execute step {chain_step.order} failed: {e}", exc_info=True)
                    step_states[str(chain_step.order)]['status'] = 'error'
                    step_states[str(chain_step.order)]['error'] = str(e)
                    break  # ferma catena su errore
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

        # Resetta lo step target a in_progress e rimuovi tutti gli step successivi
        step_states = dict(pr.step_states or {})
        step_states[str(prev_step.order)] = {'status': 'in_progress'}
        for s in steps:
            if s.order > prev_step.order:
                step_states.pop(str(s.order), None)

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
    """Test diretto Sister — bypassa workflow, passa tutti i campi al sister-agent."""
    try:
        body = request.get_json() or {}
        # Passa tutti i campi direttamente al sister-agent (non filtrare)
        sister_input = {k: v for k, v in body.items() if v}

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


# ── Report PDF pratica ─────────────────────────────────────────

# ── Registry verifiche ──────────────────────────────────────────
CHECKS_REGISTRY = [
    {
        'id': 'foglio',
        'label': 'Foglio',
        'description': 'Confronta il foglio catastale tra titolo e visura',
        'default_severity': 'error',
        'sources': ['titolo', 'visura'],
        'category': 'Dati catastali',
    },
    {
        'id': 'particella',
        'label': 'Particella/Mappale',
        'description': 'Confronta la particella (mappale) tra titolo e visura',
        'default_severity': 'error',
        'sources': ['titolo', 'visura'],
        'category': 'Dati catastali',
    },
    {
        'id': 'subalterno',
        'label': 'Subalterno',
        'description': 'Confronta il subalterno tra titolo e visura',
        'default_severity': 'error',
        'sources': ['titolo', 'visura'],
        'category': 'Dati catastali',
    },
    {
        'id': 'cognomi_proprietari',
        'label': 'Cognomi proprietari',
        'description': 'Verifica che i cognomi degli intestatari catastali corrispondano agli acquirenti del titolo',
        'default_severity': 'error',
        'sources': ['titolo', 'visura'],
        'category': 'Soggetti',
    },
    {
        'id': 'quote_proprieta',
        'label': 'Quote proprietà',
        'description': 'Confronta le quote di proprietà tra titolo e catasto',
        'default_severity': 'warning',
        'sources': ['titolo', 'visura'],
        'category': 'Soggetti',
    },
    {
        'id': 'cf_ipotecaria',
        'label': 'CF ipotecaria vs titolo',
        'description': 'Verifica che i codici fiscali dell\'ispezione ipotecaria corrispondano a quelli del titolo',
        'default_severity': 'error',
        'sources': ['titolo', 'ipotecaria'],
        'category': 'Ipotecaria',
    },
    {
        'id': 'formalita_ipotecaria',
        'label': 'Formalità ipotecaria',
        'description': 'Conta le formalità attive dall\'ispezione ipotecaria (attenzione se > 0)',
        'default_severity': 'warning',
        'sources': ['ipotecaria'],
        'category': 'Ipotecaria',
    },
    {
        'id': 'indirizzo',
        'label': 'Indirizzo',
        'description': 'Confronta l\'indirizzo dell\'immobile tra titolo e visura catastale',
        'default_severity': 'warning',
        'sources': ['titolo', 'visura'],
        'category': 'Immobile',
    },
    {
        'id': 'categoria',
        'label': 'Categoria catastale',
        'description': 'Confronta la categoria catastale tra titolo e visura',
        'default_severity': 'error',
        'sources': ['titolo', 'visura'],
        'category': 'Immobile',
    },
    {
        'id': 'rendita',
        'label': 'Rendita catastale',
        'description': 'Confronta la rendita catastale tra titolo e visura',
        'default_severity': 'error',
        'sources': ['titolo', 'visura'],
        'category': 'Immobile',
    },
    {
        'id': 'num_intestati',
        'label': 'N. intestati/acquirenti',
        'description': 'Verifica che il numero di intestatari catastali corrisponda al numero di acquirenti nel titolo',
        'default_severity': 'error',
        'sources': ['titolo', 'visura'],
        'category': 'Soggetti',
    },
    {
        'id': 'mutazioni_visura',
        'label': 'Mutazioni visura',
        'description': 'Segnala variazioni catastali rilevanti (soppressioni, frazionamenti, fusioni, ecc.) nel testo della visura',
        'default_severity': 'warning',
        'sources': ['visura'],
        'category': 'Dati catastali',
    },
]

CHECKS_BY_ID = {c['id']: c for c in CHECKS_REGISTRY}


def _build_verifiche(titolo_fields, visure_list, ipotecaria_list, checks_config=None, visura_texts=None):
    """Costruisce verifiche incrociando titolo, visure catastali e ipotecaria.

    checks_config: dict {check_id: {'enabled': bool, 'severity': str}} dal workflow.
    Se None, usa i default del registry.
    visura_texts: lista di stringhe con il testo estratto dai PDF delle visure catastali.
    """
    import unicodedata

    def _norm(v):
        if v is None:
            return ''
        s = str(v).strip().lower()
        s = unicodedata.normalize('NFD', s)
        s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
        return re.sub(r'\s+', ' ', s)

    def _tget(field, *aliases):
        """Cerca un campo nel titolo con alias multipli."""
        for k in (field, *aliases):
            if k in titolo_fields:
                return str(titolo_fields[k][1])
        return ''

    def _is_enabled(check_id):
        """Verifica se un check è abilitato nella config."""
        if not checks_config:
            return True
        cc = checks_config.get(check_id, {})
        return cc.get('enabled', True)

    def _severity(check_id, raw_esito):
        """Applica severity override: se il check è ok resta ok, altrimenti usa la severity configurata."""
        if raw_esito == 'ok':
            return 'ok'
        if not checks_config:
            return raw_esito
        cc = checks_config.get(check_id, {})
        return cc.get('severity', raw_esito)

    verifiche = []
    v0 = visure_list[0] if visure_list else {}

    # ── Dati comuni per più check ──
    catasto_nomi = []  # nomi completi intestatari catastali
    _seen_nominativi = set()
    for v in visure_list:
        for i in v.get('intestati', []):
            nom = i.get('nominativo', '').strip()
            if nom and nom not in _seen_nominativi:
                _seen_nominativi.add(nom)
                catasto_nomi.append(nom)

    _acq_tuple = titolo_fields.get('acquirenti') or titolo_fields.get('parti_acquirenti') or (None, None)
    titolo_acq_raw = _acq_tuple[1]
    titolo_nomi = []  # nomi completi acquirenti titolo
    if isinstance(titolo_acq_raw, list):
        for a in titolo_acq_raw:
            if isinstance(a, dict):
                n = a.get('nominativo', '') or a.get('cognome', '')
                if not n and a.get('cognome'):
                    n = (a.get('cognome', '') + ' ' + a.get('nome', '')).strip()
                titolo_nomi.append(str(n).strip())
            else:
                titolo_nomi.append(str(a).strip())
    elif isinstance(titolo_acq_raw, str) and titolo_acq_raw:
        titolo_nomi = [p.strip() for p in titolo_acq_raw.split(';') if p.strip()]
    # Alias per compatibilità (conteggio intestati, etc.)
    catasto_cognomi = catasto_nomi
    titolo_cognomi = titolo_nomi

    # ── 1. Foglio / Particella / Subalterno ──
    if v0:
        for check_id, field, aliases, label in [
            ('foglio', 'foglio', [], 'Foglio'),
            ('particella', 'particella', ['mappale', 'numero_particella'], 'Particella/Mappale'),
            ('subalterno', 'subalterno', ['sub'], 'Subalterno'),
        ]:
            if not _is_enabled(check_id):
                continue
            val_t = _tget(field, *aliases)
            val_c = v0.get(field, v0.get('FOGLIO' if field == 'foglio' else field.upper(), ''))
            if val_t or val_c:
                t_parts = set(_norm(p) for p in str(val_t).split(';') if p.strip())
                c_norm = _norm(val_c)
                match = c_norm in t_parts if t_parts and c_norm else not (t_parts and c_norm)
                raw = 'ok' if match else 'error'
                verifiche.append({
                    'check_id': check_id,
                    'label': label,
                    'val_titolo': val_t or '\u2014',
                    'val_catasto': val_c or '\u2014',
                    'esito': _severity(check_id, raw),
                })

    # ── 2. Cognomi proprietari ──
    if _is_enabled('cognomi_proprietari') and (catasto_nomi or titolo_nomi):
        # Confronto a parole: per ogni persona catastale, almeno un cognome
        # deve comparire in almeno un nome del titolo (e viceversa)
        cat_words = set()
        for n in catasto_nomi:
            cat_words.update(_norm(w) for w in n.split() if len(w) > 2)
        tit_words = set()
        for n in titolo_nomi:
            tit_words.update(_norm(w) for w in n.split() if len(w) > 2)
        match = bool(cat_words & tit_words) if cat_words and tit_words else not (cat_words and tit_words)
        raw = 'ok' if match else 'error'
        verifiche.append({
            'check_id': 'cognomi_proprietari',
            'label': 'Cognomi proprietari',
            'val_titolo': ', '.join(titolo_nomi) or '\u2014',
            'val_catasto': ', '.join(catasto_nomi) or '\u2014',
            'esito': _severity('cognomi_proprietari', raw),
        })

    # ── 3. Quote proprietà ──
    if _is_enabled('quote_proprieta'):
        catasto_quote = []
        _seen_quote = set()
        for v in visure_list:
            for i in v.get('intestati', []):
                if i.get('quota'):
                    key = (i.get('nominativo', ''), i['quota'])
                    if key not in _seen_quote:
                        _seen_quote.add(key)
                        catasto_quote.append(i['quota'])
        val_quote_t = _tget('quote', 'quota', 'quote_proprieta')
        if catasto_quote or val_quote_t:
            if _norm(val_quote_t) == _norm(', '.join(catasto_quote)):
                raw = 'ok'
            elif not val_quote_t or not catasto_quote:
                raw = 'warning'
            else:
                raw = 'error'
            verifiche.append({
                'check_id': 'quote_proprieta',
                'label': 'Quote propriet\u00e0',
                'val_titolo': val_quote_t or '\u2014',
                'val_catasto': ', '.join(catasto_quote) or '\u2014',
                'esito': _severity('quote_proprieta', raw),
            })

    # ── 4. CF ipotecaria vs titolo ──
    if _is_enabled('cf_ipotecaria') and ipotecaria_list:
        ipot_cfs = [isp.get('codiceFiscale', '') for isp in ipotecaria_list if isp.get('codiceFiscale')]
        val_cf_t = _tget('cf_acquirenti', 'codice_fiscale', 'cf', 'codici_fiscali')
        titolo_cfs = [p.strip() for p in val_cf_t.split(';') if p.strip()] if val_cf_t else []
        if ipot_cfs:
            tit_set = set(_norm(c) for c in titolo_cfs)
            match = all(_norm(cf) in tit_set for cf in ipot_cfs) if titolo_cfs else True
            raw = 'ok' if match else 'error'
            verifiche.append({
                'check_id': 'cf_ipotecaria',
                'label': 'CF ipotecaria vs titolo',
                'val_titolo': ', '.join(titolo_cfs) or '\u2014',
                'val_catasto': ', '.join(ipot_cfs),
                'esito': _severity('cf_ipotecaria', raw),
            })

    # ── 5. Formalità ipotecaria ──
    if _is_enabled('formalita_ipotecaria') and ipotecaria_list:
        all_form = []
        attive = 0
        for isp in ipotecaria_list:
            for f in isp.get('formalita', []):
                all_form.append(f)
                if f.get('flagCancellazione') != '1':
                    attive += 1
        if all_form:
            raw = 'ok' if attive == 0 else 'warning'
            verifiche.append({
                'check_id': 'formalita_ipotecaria',
                'label': 'Formalit\u00e0 ipotecaria',
                'val_titolo': '\u2014',
                'val_catasto': f'{len(all_form)} formalit\u00e0 ({attive} attive)',
                'esito': _severity('formalita_ipotecaria', raw),
            })

    # ── 6. Indirizzo ──
    if _is_enabled('indirizzo') and v0:
        val_ind_t = _tget('indirizzo', 'indirizzo_immobile')
        val_ind_c = v0.get('indirizzo', '')
        if val_ind_t or val_ind_c:
            match = _norm(val_ind_t) == _norm(val_ind_c) if val_ind_t and val_ind_c else True
            raw = 'ok' if match else 'warning'
            verifiche.append({
                'check_id': 'indirizzo',
                'label': 'Indirizzo',
                'val_titolo': val_ind_t or '\u2014',
                'val_catasto': val_ind_c or '\u2014',
                'esito': _severity('indirizzo', raw),
            })

    # ── 7. Categoria / Rendita ──
    if v0:
        for check_id, field, label in [('categoria', 'categoria', 'Categoria'), ('rendita', 'rendita', 'Rendita')]:
            if not _is_enabled(check_id):
                continue
            val_t = _tget(field)
            val_c = v0.get(field, '')
            if val_t or val_c:
                match = _norm(val_t) == _norm(val_c) if val_t and val_c else True
                raw = 'ok' if match else 'error'
                verifiche.append({
                    'check_id': check_id,
                    'label': label,
                    'val_titolo': val_t or '\u2014',
                    'val_catasto': val_c or '\u2014',
                    'esito': _severity(check_id, raw),
                })

    # ── 8. Numero intestati vs acquirenti ──
    if _is_enabled('num_intestati'):
        n_cat = len(catasto_cognomi)
        n_tit = len(titolo_cognomi)
        if n_cat > 0 or n_tit > 0:
            raw = 'ok' if n_cat == n_tit else 'error'
            verifiche.append({
                'check_id': 'num_intestati',
                'label': 'N. intestati/acquirenti',
                'val_titolo': str(n_tit) if n_tit else '\u2014',
                'val_catasto': str(n_cat) if n_cat else '\u2014',
                'esito': _severity('num_intestati', raw),
            })

    # ── 9. Mutazioni visura ──
    if _is_enabled('mutazioni_visura') and visura_texts:
        full_text = '\n'.join(visura_texts).lower()
        # Normalizza accenti per matching robusto
        full_text_norm = unicodedata.normalize('NFD', full_text)
        full_text_norm = ''.join(c for c in full_text_norm if unicodedata.category(c) != 'Mn')

        # Rimuovi frasi standard che contengono stem ma non indicano mutazioni
        for _bl in ['dati identificativi']:
            full_text_norm = full_text_norm.replace(_bl, '')

        # Pattern per severità (ordine: alta → bassa). Cerca radici.
        _TRIGGERS = [
            # (severità, radici da cercare, messaggio)
            ('error', ['soppress', 'identificativ'],
             'Identificativo variato o soppresso: F/M/S potrebbero non essere più validi. Controlla i nuovi identificativi.'),
            ('error', ['frazionament', 'fusione', 'accorpamento', 'tipo mappale'],
             'Particella frazionata/fusa o cambiata di natura: confini e consistenza possono essere cambiati.'),
            ('warning', ['allineamento mappe', 'riordino fondiario'],
             'Foglio/subalterno modificati per operazione cartografica (non compravendita): stesso immobile, identificativi diversi.'),
            ('warning', ['costituzion'],
             'Nuovo identificativo costituito: verifica che corrisponda all\'immobile cercato.'),
        ]
        # Parole "variazione di X" innocue — NON sono trigger
        _SAFE_VARIATIONS = [
            'variazione toponomastica', 'variazione di classamento',
            'variazione di consistenza', 'variazione della rendita',
            'variazione colturale',
        ]

        best_severity = None
        best_msg = ''
        severity_rank = {'error': 3, 'warning': 2, 'ok': 0}

        for severity, stems, msg in _TRIGGERS:
            for stem in stems:
                if stem in full_text_norm:
                    if severity_rank.get(severity, 0) > severity_rank.get(best_severity, 0):
                        best_severity = severity
                        best_msg = msg
                    break

        # Estrai nuovi identificativi se soppressione/variazione identificativo
        extra_info = ''
        if best_severity == 'error' and ('soppress' in full_text_norm or 'identificativ' in full_text_norm):
            # Cerca sezione dopo "ha originato e/o variato i seguenti immobili"
            marker = 'ha originato'
            idx = full_text_norm.find(marker)
            if idx >= 0:
                # Prendi tutto fino alla prossima sezione "Situazione" o fine testo
                after = full_text_norm[idx:]
                end = after.find('situazione dell')
                if end > 0:
                    after = after[:end]
                # Cerca pattern "Foglio X Particella Y Subalterno Z"
                id_matches = re.findall(
                    r'foglio\s+(\d+)\s+particella\s+(\d+)\s+subalterno\s+(\d+)',
                    after, re.IGNORECASE)
                if id_matches:
                    # Raggruppa per Foglio/Particella, riassumi subalterni
                    from collections import defaultdict
                    groups = defaultdict(list)
                    for f, p, s in id_matches:
                        groups[(f, p)].append(int(s))
                    parts = []
                    for (f, p), subs in sorted(groups.items()):
                        subs.sort()
                        if len(subs) > 3:
                            parts.append(f"F.{f} P.{p} Sub.{subs[0]}-{subs[-1]} ({len(subs)})")
                        else:
                            parts.append(f"F.{f} P.{p} Sub.{','.join(str(s) for s in subs)}")
                    extra_info = ' Nuovi identificativi: ' + '; '.join(parts)

        if best_severity:
            verifiche.append({
                'check_id': 'mutazioni_visura',
                'label': 'Mutazioni visura',
                'val_titolo': '\u2014',
                'val_catasto': best_msg + extra_info,
                'esito': _severity('mutazioni_visura', best_severity),
            })

    return verifiche


@pratiche_bp.route('/checks-registry', methods=['GET'])
def get_checks_registry():
    """Restituisce il registry dei check disponibili."""
    return jsonify(CHECKS_REGISTRY)


@pratiche_bp.route('/practice/<practice_id>/report', methods=['GET'])
def generate_practice_report(practice_id):
    """Genera report PDF riepilogativo della pratica."""
    try:
        user = request.args.get('user', '')

        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if not pr:
            return jsonify({"error": "Pratica non trovata"}), 404

        result_data = pr.result_data or {}
        step_states = pr.step_states or {}
        files_data = result_data.get('files', {})

        # ── Classifica documenti ──
        titolo_fields = {}   # key_lower -> (original_key, value)
        acquirenti_docs = {}
        visure_list = []
        ipotecaria_list = []

        for fhash, fdata in files_data.items():
            doc_id = (fdata.get('identification', {}).get('documentId', '') or fhash).strip()
            extraction = fdata.get('extraction', {}).get('data', {})
            if not extraction or not isinstance(extraction, dict):
                continue
            dl = doc_id.lower()
            if dl.startswith('visura') or dl.startswith('ipotecaria'):
                continue
            elif any(x in dl for x in ['carta', 'identit', 'patente', 'passaporto',
                                        'codice fiscale', 'tessera sanitaria', 'tessera_sanitaria']):
                acquirenti_docs[doc_id] = extraction
            else:
                for k, v in extraction.items():
                    kl = k.lower()
                    if v and kl not in titolo_fields:
                        titolo_fields[kl] = (k, v)

        # Visure/ipotecaria da step exec_result
        for order, ss in step_states.items():
            if ss.get('status') != 'completed':
                continue
            er = ss.get('exec_result', {})
            if er.get('type') == 'SISTER_VISURA':
                visure_list.extend(er.get('visure', []))
            elif er.get('type') == 'SISTER_IPOTECARIA':
                ipotecaria_list.extend(er.get('ispezioni', []))

        # ── 1. Immobile ──
        IMMOBILE_KEYS = ['comune', 'provincia', 'indirizzo', 'foglio', 'particella', 'mappale', 'subalterno']
        immobile = []
        seen_imm = set()
        for ik in IMMOBILE_KEYS:
            if ik in titolo_fields:
                label = titolo_fields[ik][0].replace('_', ' ').title()
                immobile.append((label, str(titolo_fields[ik][1])))
                seen_imm.add(ik)
        # Fallback da visura
        if visure_list and 'indirizzo' not in seen_imm:
            ind = visure_list[0].get('indirizzo', '')
            if ind:
                immobile.append(('Indirizzo', ind))

        # ── 2. Dati dal titolo ──
        EXCLUDE = set(IMMOBILE_KEYS + ['acquirenti', 'venditori', 'intestati', 'parti',
                                         'soggetti', 'parti_acquirenti'])
        titolo = []
        for kl, (label, val) in titolo_fields.items():
            if kl in EXCLUDE:
                continue
            if isinstance(val, list):
                if val and isinstance(val[0], dict):
                    val = '; '.join(
                        ', '.join(f'{dk}: {dv}' for dk, dv in item.items() if dv)
                        for item in val
                    )
                else:
                    val = '; '.join(str(x) for x in val)
            elif isinstance(val, dict):
                val = ', '.join(f'{dk}: {dv}' for dk, dv in val.items() if dv)
            titolo.append((label.replace('_', ' ').title(), str(val)))

        # ── 3. Venditori (intestati catasto) ──
        venditori = []
        seen_v = set()
        for v in visure_list:
            for i in v.get('intestati', []):
                nom = i.get('nominativo', '')
                if nom and nom not in seen_v:
                    seen_v.add(nom)
                    venditori.append({
                        'nominativo': nom,
                        'cf': i.get('cf', ''),
                        'diritto': i.get('diritto', ''),
                        'quota': i.get('quota', ''),
                    })

        # ── 4. Acquirenti (da CI/CF) ──
        acquirenti = []
        for doc_id, fields in acquirenti_docs.items():
            nome = fields.get('nome', fields.get('NOME', ''))
            cognome = fields.get('cognome', fields.get('COGNOME', ''))
            cf = fields.get('codice_fiscale', fields.get('CODICE_FISCALE', fields.get('cf', '')))
            if nome or cognome:
                acquirenti.append({
                    'nominativo': f'{cognome} {nome}'.strip(),
                    'cf': cf or '',
                })

        # ── 5. Analisi visure catastali (parsing PDF) ──
        visura_texts = []
        analisi_catastali = []
        try:
            from app.services.visura_parser import parse_visura_text
            visura_pfiles = db.query(PracticeFile).filter_by(practice_id=practice_id).all()
            for pf in visura_pfiles:
                fn = (pf.file_name or '').lower()
                if 'catastale' not in fn and 'visura' not in fn:
                    continue
                text = ''
                if pf.ocr_text:
                    text = pf.ocr_text
                elif pf.data and pf.mime_type and 'pdf' in pf.mime_type:
                    try:
                        import pypdf
                        from io import BytesIO as _BytesIO
                        reader = pypdf.PdfReader(_BytesIO(bytes(pf.data)))
                        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
                    except Exception:
                        pass
                if text.strip():
                    visura_texts.append(text)
                    parsed = parse_visura_text(text)
                    if parsed:
                        parsed['_file_name'] = pf.file_name
                        analisi_catastali.append(parsed)
        except Exception as e:
            logger.warning(f"Report: parsing visure catastali: {e}")

        # ── 6. Verifiche ──
        from app.models import Workflow
        checks_config = None
        if pr.workflow_id:
            wf = db.query(Workflow).get(pr.workflow_id)
            if wf and wf.config:
                checks_config = wf.config.get('checks_config')
        verifiche = _build_verifiche(titolo_fields, visure_list, ipotecaria_list, checks_config,
                                     visura_texts=visura_texts)

        # Applica override manuali dallo step verifica_report (se confermato)
        vr_overrides = {}
        for order, ss in step_states.items():
            er = ss.get('exec_result', {})
            if er.get('type') == 'VERIFICA_REPORT' and ss.get('overrides'):
                vr_overrides = ss['overrides']
                break
        if vr_overrides:
            for v in verifiche:
                cid = v.get('check_id', '')
                if cid in vr_overrides:
                    v['esito'] = vr_overrides[cid]['esito']
                    nota = vr_overrides[cid].get('nota', '')
                    if nota:
                        v['nota_override'] = nota

        # ── 6. Ipotecaria ──
        ipotecaria = []
        for isp in ipotecaria_list:
            sogg = ', '.join(
                f"{s.get('cognome', '')} {s.get('nome', '')}" for s in isp.get('soggetti', [])
            )
            formalita = []
            for f in isp.get('formalita', []):
                formalita.append({
                    'descrizione': f.get('descrizione', '?'),
                    'data': f.get('data', ''),
                    'qualifica': f.get('qualifica', ''),
                    'specie_atto': f.get('specieAtto', ''),
                    'cancellata': f.get('flagCancellazione') == '1',
                })
            ipotecaria.append({
                'nominativo': sogg or isp.get('codiceFiscale', '?'),
                'cf': isp.get('codiceFiscale', ''),
                'num_formalita': isp.get('num_formalita', 0),
                'formalita': formalita,
                'costo': isp.get('costo'),
            })

        # ── 7. Riepilogo ──
        total = len(verifiche)
        ok_n = sum(1 for v in verifiche if v['esito'] == 'ok')
        err_n = sum(1 for v in verifiche if v['esito'] == 'error')
        warn_n = sum(1 for v in verifiche if v['esito'] == 'warning')
        criticita = [v['label'] for v in verifiche if v['esito'] == 'error']

        report_data = {
            'practice_id': practice_id,
            'date': pr.created_at.strftime('%d/%m/%Y') if pr.created_at else '',
            'user': user,
            'immobile': immobile,
            'titolo': titolo,
            'venditori': venditori,
            'acquirenti': acquirenti,
            'verifiche': verifiche,
            'ipotecaria': ipotecaria,
            'analisi_catastali': analisi_catastali,
            'riepilogo': {
                'total': total,
                'ok': ok_n,
                'errors': err_n,
                'warnings': warn_n,
                'criticita': criticita,
            },
        }

        from app.services.pdf_service import generate_report_pdf
        pdf_bytes = generate_report_pdf(report_data)

        return Response(
            pdf_bytes,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="report_{practice_id}.pdf"'}
        )
    except Exception as e:
        logger.error(f"Generate report error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
