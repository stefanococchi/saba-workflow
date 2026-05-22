"""Blueprint API per Pratiche Documentali (proxy verso Agent Orchestrator)."""
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
from app.services import ao_service
from app import db_session as db
from app.models import PracticeResult, PracticeFile, Participant, WorkflowStep, StepType, ParticipantStatus, ExecutionStatus, Execution
import json
import logging
import re

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
    """Completa lo step corrente e avanza al prossimo. Per DOCUMENT_CHECK usa validate/reject."""
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

        # Raccogli dati estratti dalla pratica per il contesto dello step
        extracted_data = {}
        if pr.result_data and isinstance(pr.result_data, dict):
            for fhash, fdata in (pr.result_data.get('files', {})).items():
                if fdata.get('extraction', {}).get('data'):
                    doc_type = fdata.get('identification', {}).get('documentId', fhash)
                    extracted_data[doc_type] = fdata['extraction']['data']

        # Segna step corrente come completato
        step_states[str(current_order)] = {
            'status': 'skipped' if action == 'skip' else 'completed',
            'completed_at': datetime.utcnow().isoformat(),
            'result': step_result,
            'extracted_data': extracted_data,
        }

        # Esegui azioni automatiche dello step (email, whatsapp, ecc.)
        step_type = current_step.type.name
        exec_result = {}
        if action != 'skip' and step_type in ('EMAIL', 'WHATSAPP', 'WEBHOOK'):
            exec_result = _execute_backoffice_step(current_step, pr, body)
            step_states[str(current_order)]['exec_result'] = exec_result

        # Avanza al prossimo step
        next_step = next((s for s in steps if s.order > current_order), None)
        if next_step:
            pr.current_step_order = next_step.order
            step_states[str(next_step.order)] = {'status': 'in_progress'}
        else:
            # Workflow completato
            pr.current_step_order = None

        pr.step_states = step_states
        db.commit()

        return jsonify({
            "ok": True,
            "completed_step": current_order,
            "completed_type": step_type,
            "next_step_order": next_step.order if next_step else None,
            "next_step_name": next_step.name if next_step else None,
            "workflow_completed": next_step is None,
            "exec_result": exec_result,
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

    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Execute backoffice step error: {e}")

    return result
