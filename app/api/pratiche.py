"""Blueprint API per Pratiche Documentali (proxy verso Agent Orchestrator)."""
from flask import Blueprint, request, jsonify, Response
from app.services import ao_service
from app import db_session as db
from app.models import PracticeResult
import json
import logging

logger = logging.getLogger(__name__)

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


@pratiche_bp.route('/practice/<agent_id>/<practice_id>/process', methods=['POST'])
def ao_practice_process(agent_id, practice_id):
    """Processa una pratica: carica file e avvia identify+extract."""
    try:
        files = {}
        idx = 0
        for key in request.files:
            upload = request.files[key]
            content = upload.read()
            files[f"file_{idx}"] = (content, upload.content_type, upload.filename)
            idx += 1
        result = ao_service.practice_process(
            agent_id, practice_id, files=files if files else None,
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"AO practice process: {e}")
        return jsonify({"error": str(e)}), 500


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
        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if pr:
            pr.result_data = body.get('result_data')
            pr.agent_id = body.get('agent_id', pr.agent_id)
            pr.agent_name = body.get('agent_name', pr.agent_name)
        else:
            pr = PracticeResult(
                practice_id=practice_id,
                agent_id=body.get('agent_id', ''),
                agent_name=body.get('agent_name', ''),
                result_data=body.get('result_data'),
            )
            db.add(pr)
        db.commit()
        return jsonify({"ok": True, "data": pr.to_dict()})
    except Exception as e:
        db.rollback()
        logger.error(f"Save practice result: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/results', methods=['GET'])
def list_practice_results():
    """Lista tutte le pratiche salvate."""
    try:
        results = db.query(PracticeResult).order_by(PracticeResult.updated_at.desc()).all()
        return jsonify({"results": [r.to_dict() for r in results]})
    except Exception as e:
        logger.error(f"List practice results: {e}")
        return jsonify({"error": str(e)}), 500


@pratiche_bp.route('/results/<practice_id>', methods=['DELETE'])
def delete_practice_result(practice_id):
    """Elimina risultato pratica dal database."""
    try:
        pr = db.query(PracticeResult).filter_by(practice_id=practice_id).first()
        if pr:
            db.delete(pr)
            db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        logger.error(f"Delete practice result: {e}")
        return jsonify({"error": str(e)}), 500
