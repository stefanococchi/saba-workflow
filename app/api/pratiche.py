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
            {"file_name": f.file_name, "mime_type": f.mime_type}
            for f in files
        ]})
    except Exception as e:
        logger.error(f"List practice files: {e}")
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
                # Aggiorna file esistente
                pf = db.query(PracticeFile).filter_by(practice_id=practice_id, file_name=upload.filename).first()
                if pf:
                    pf.data = content
                    pf.mime_type = upload.content_type or 'application/octet-stream'
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

    _processing_jobs[practice_id] = {
        'status': 'running',
        'progress': 0,
        'total': len(to_process),
        'skipped': len(files_data) - len(to_process),
        'results': [],
        'error': None,
        'started_at': datetime.utcnow().isoformat(),
    }

    from flask import current_app
    app = current_app._get_current_object()

    stop_event = threading.Event()
    _stop_flags[practice_id] = stop_event

    def _bg_process():
        with app.app_context():
            from app import db_session as bg_db
            from sqlalchemy.orm.attributes import flag_modified
            job = _processing_jobs[practice_id]
            try:
                for i, (fn, mt, data) in enumerate(to_process):
                    if stop_event.is_set():
                        job['status'] = 'stopped'
                        logger.info(f"BG process stopped by user at file {i+1}/{len(to_process)}")
                        break

                    MAX_RETRIES = 3
                    RETRY_DELAYS = [5, 15, 30]  # secondi tra i tentativi
                    last_error = None
                    success = False

                    for attempt in range(MAX_RETRIES):
                        if stop_event.is_set():
                            break
                        try:
                            if attempt > 0:
                                delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
                                logger.info(f"BG file {fn}: retry {attempt + 1}/{MAX_RETRIES} tra {delay}s...")
                                import time as _time
                                _time.sleep(delay)

                            files = {f"file_0": (data, mt, fn)}
                            result = ao_service.practice_process(agent_id, practice_id, files=files)
                            output = result.get('output', {})
                            info = output.get('info', output)
                            ao_files = info.get('files', {})
                            # Log documentId ritornati dall'AO (per debug matching doc_types)
                            for _fh, _fd in ao_files.items():
                                _did = _fd.get('identification', {}).get('documentId', '?')
                                logger.info(f"BG file {fn}: AO documentId='{_did}' hash={_fh[:12]}")

                            # Leggi dal DB fresco (refresh forza rilettura dopo commit precedente)
                            bg_pr = bg_db.query(PracticeResult).filter_by(practice_id=practice_id).first()
                            if bg_pr:
                                bg_db.refresh(bg_pr)
                                rd = dict(bg_pr.result_data or {})
                                if 'files' not in rd:
                                    rd['files'] = {}
                                for fh, fd in ao_files.items():
                                    rd['files'][fh] = fd
                                bg_pr.result_data = rd
                                flag_modified(bg_pr, 'result_data')
                                bg_db.commit()
                                logger.info(f"BG file {fn}: AO returned {len(ao_files)}, total in DB={len(rd['files'])}")
                            else:
                                logger.error(f"BG process: PracticeResult not found for {practice_id}")

                            job['results'].append({'file': fn, 'ok': True})
                            success = True
                            break  # successo, esci dal retry loop

                        except Exception as e:
                            last_error = str(e)
                            logger.warning(f"BG file {fn}: attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")

                    if not success and not stop_event.is_set():
                        job['results'].append({'file': fn, 'ok': False, 'error': last_error})
                        logger.error(f"BG file {fn}: all {MAX_RETRIES} attempts failed: {last_error}")

                        # Salva errore nel DB per consultazione da UI
                        try:
                            bg_pr = bg_db.query(PracticeResult).filter_by(practice_id=practice_id).first()
                            if bg_pr:
                                bg_db.refresh(bg_pr)
                                rd = dict(bg_pr.result_data or {})
                                if '_ao_errors' not in rd:
                                    rd['_ao_errors'] = []
                                rd['_ao_errors'].append({
                                    'file': fn,
                                    'error': last_error,
                                    'attempts': MAX_RETRIES,
                                    'at': datetime.utcnow().isoformat(),
                                })
                                bg_pr.result_data = rd
                                flag_modified(bg_pr, 'result_data')
                                bg_db.commit()
                        except Exception:
                            pass  # non bloccare il flusso per un errore di logging

                    job['progress'] = i + 1

                if job['status'] != 'stopped':
                    job['status'] = 'completed'
                    logger.info(f"BG process completed for {practice_id}")
            except Exception as e:
                job['status'] = 'error'
                job['error'] = str(e)
                logger.error(f"BG process-all error: {e}")
            finally:
                _stop_flags.pop(practice_id, None)

    t = threading.Thread(target=_bg_process, daemon=True)
    t.start()

    return jsonify({
        "ok": True,
        "total": len(to_process),
        "skipped": len(files_data) - len(to_process),
    })


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
    """Polling stato elaborazione in background."""
    job = _processing_jobs.get(practice_id)
    if not job:
        return jsonify({"status": "none"})
    return jsonify(job)


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
    """Genera sintesi di un documento notarile."""
    try:
        prompt = request.form.get("prompt", "")
        agent_id = request.form.get("agent_id", "")
        document_type_id = request.form.get("documentTypeId")
        document_type_label = request.form.get("documentTypeLabel")
        model = request.form.get("model", "gemini-2.5-flash")

        upload = request.files.get("file")
        if not upload:
            return jsonify({"error": "File mancante"}), 400

        content = upload.read()
        result = ao_service.sintesi_generate(
            agent_id, prompt, content, upload.content_type, upload.filename,
            document_type_id=document_type_id,
            document_type_label=document_type_label,
            model=model,
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO sintesi generate: {e}")
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
        for s in steps:
            ss = step_states.get(str(s.order), {})
            if ss.get('status') == 'completed' and ss.get('extracted_data'):
                accumulated_data.update(ss['extracted_data'])

        return jsonify({
            "has_workflow": True,
            "workflow_id": pr.workflow_id,
            "workflow_name": workflow.name,
            "current_step_order": pr.current_step_order,
            "total_steps": len(steps),
            "steps": [{
                'order': s.order,
                'name': s.name,
                'type': s.type.name,
                'config': s.skip_conditions or {},
                'state': step_states.get(str(s.order), {'status': 'pending'}),
            } for s in steps],
            "accumulated_data": accumulated_data,
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

        # ── 2. Salva lo step corrente come completato (atomico) ──
        step_type = current_step.type.name
        step_states[str(current_order)] = {
            'status': 'skipped' if action == 'skip' else 'completed',
            'completed_at': datetime.utcnow().isoformat(),
            'result': step_result,
            'extracted_data': extracted_data,
            'validated_files': validated_files,
        }

        # Esegui azioni automatiche dello step corrente (email, whatsapp, ecc.)
        exec_result = {}
        if action != 'skip' and step_type in ('EMAIL', 'WHATSAPP', 'WEBHOOK', 'SISTER_VISURA'):
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

            # Auto-esegui il prossimo step se è di tipo automatico
            next_type = next_step.type.name
            if next_type in ('EMAIL', 'WHATSAPP', 'WEBHOOK', 'SISTER_VISURA'):
                try:
                    next_exec_result = _execute_backoffice_step(next_step, pr, body)
                    step_states[str(next_step.order)]['status'] = 'completed'
                    step_states[str(next_step.order)]['completed_at'] = datetime.utcnow().isoformat()
                    step_states[str(next_step.order)]['exec_result'] = next_exec_result

                    # Avanza ancora dopo l'auto-esecuzione
                    after_next = next((s for s in steps if s.order > next_step.order), None)
                    if after_next:
                        pr.current_step_order = after_next.order
                        step_states[str(after_next.order)] = {'status': 'in_progress'}
                    else:
                        pr.current_step_order = None
                except Exception as e:
                    logger.error(f"Auto-execute next step {next_step.order} failed: {e}")
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


def _execute_backoffice_step(step, practice_result, body):
    """Esegue uno step automatico (email/whatsapp/webhook) nel contesto di una pratica."""
    step_type = step.type.name
    config = step.skip_conditions or {}
    result = {'type': step_type}

    try:
        if step_type == 'EMAIL':
            from app.services.email_service import EmailService
            to_email = config.get('custom_to', '') or body.get('to_email', '')
            subject = config.get('subject', step.subject or '')
            body_html = step.body_template or ''
            if to_email and subject:
                ok = EmailService.send_email(to_email=to_email, subject=subject, body_html=body_html)
                result['sent'] = ok
                result['to'] = to_email
            else:
                result['error'] = 'Email o subject mancante'

        elif step_type == 'WEBHOOK':
            import requests as req
            url = config.get('webhook_url', '')
            if url:
                r = req.post(url, json={
                    'practice_id': practice_result.practice_id,
                    'step': step.name,
                    'result_data': practice_result.result_data,
                }, timeout=30)
                result['status_code'] = r.status_code
            else:
                result['error'] = 'URL webhook mancante'

        elif step_type == 'WHATSAPP':
            result['note'] = 'WhatsApp non ancora implementato per workflow pratica'

        elif step_type == 'SISTER_VISURA':
            result = _execute_sister_visura(step, practice_result, config)

    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Execute backoffice step error: {e}")

    return result


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


def _execute_sister_visura(step, practice_result, config):
    """Chiama sister-agent con dati catastali dal contesto accumulato della pratica."""
    result = {'type': 'SISTER_VISURA'}

    # Trova agent_id per sister-agent
    sister_agent_id = config.get('sister_agent_id', '')
    if not sister_agent_id:
        agents_list = ao_service.list_agents()
        sa = next((a for a in agents_list if 'sister' in (a.get('name', '') or '').lower()), None)
        if sa:
            sister_agent_id = sa['id']
        else:
            result['error'] = 'Agente sister-agent non trovato'
            return result

    # Raccogli dati catastali dal contesto accumulato (step precedenti)
    accumulated = {}
    step_states = practice_result.step_states or {}
    for order_key, state in step_states.items():
        if state.get('status') == 'completed' and state.get('extracted_data'):
            for doc_type, fields in state['extracted_data'].items():
                if isinstance(fields, dict):
                    accumulated.update(fields)

    logger.info(f"Sister visura accumulated data keys: {list(accumulated.keys())}")
    if accumulated:
        logger.info(f"Sister visura accumulated sample: { {k: v for k, v in list(accumulated.items())[:10]} }")

    # Mapping: campo estratto → campo sister input
    field_mapping = config.get('field_mapping', {})
    sister_input = {
        'operation': config.get('operation', 'visuraStorica'),
        'tipoCatasto': config.get('tipo_catasto', 'F'),
        'tipoVisura': config.get('tipo_visura', 'sintetica'),
    }

    # Applica mapping: per ogni campo sister, cerca il valore nel contesto
    mapping_fields = {
        'provincia': 'provincia',
        'comune': 'comune',
        'foglio': 'foglio',
        'particella': 'particella',
        'subalterno': 'subalterno',
    }
    # Merge mapping custom dalla config
    mapping_fields.update(field_mapping)

    for sister_key, source_key in mapping_fields.items():
        # Cerca nel contesto accumulato (case-insensitive)
        val = None
        for k, v in accumulated.items():
            if k.lower() == source_key.lower() or k.lower().replace(' ', '_') == source_key.lower():
                val = v
                break
        # Override manuale dal body della request
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
    logger.info(f"Sister visura input: {sister_input}")

    # Chiama sister-agent
    try:
        run_result = ao_service.run_agent(sister_agent_id, sister_input)
        task_result = ao_service.poll_task(run_result['taskId'], max_wait=120.0)
        output = task_result.get('output', {})

        # Cerca file PDF nell'output
        file_data = None
        file_name = f"visura_{sister_input.get('comune', 'visura')}_{sister_input.get('foglio', '')}_{sister_input.get('particella', '')}.pdf"

        # L'output potrebbe contenere il file in diversi formati
        if isinstance(output, dict):
            # Cerca binary/file data
            for key in ('file', 'pdf', 'data', 'document', 'binary'):
                if key in output and output[key]:
                    file_data = output[key]
                    break
            if output.get('fileName'):
                file_name = output['fileName']

        # Se abbiamo il file, salvalo nella pratica
        if file_data:
            import base64
            if isinstance(file_data, str):
                # Probabilmente base64
                content = base64.b64decode(file_data)
            elif isinstance(file_data, dict) and file_data.get('data'):
                content = base64.b64decode(file_data['data'])
            else:
                content = file_data

            # Salva come PracticeFile
            existing = db.query(PracticeFile).filter_by(
                practice_id=practice_result.practice_id, file_name=file_name
            ).first()
            if existing:
                existing.data = content
                existing.mime_type = 'application/pdf'
            else:
                db.add(PracticeFile(
                    practice_id=practice_result.practice_id,
                    file_name=file_name,
                    mime_type='application/pdf',
                    data=content,
                ))
            db.flush()

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
