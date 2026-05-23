"""
Connector per Agent Orchestrator (ao-workflows) — sync version for Flask.
Gestisce pratiche documentali (conformita-titoli, anti-riciclaggio, post-stipula-sintesi).
"""
import base64
import json
import logging
import time
from pathlib import Path

import requests
from flask import current_app

logger = logging.getLogger("saba-workflow.ao")

_TIMEOUT = 120


def _get_config():
    """Read AO config from Flask current_app."""
    return {
        'base_url': current_app.config.get('AO_BASE_URL', '').rstrip('/'),
        'token': current_app.config.get('AO_SERVICE_TOKEN', ''),
        'team_id': current_app.config.get('AO_TEAM_ID', ''),
    }


def _headers(accept="application/json"):
    cfg = _get_config()
    return {
        "x-api-key": cfg['token'],
        "Content-Type": "application/json",
        "Accept": accept,
    }


def _extract_useful_output(raw_output):
    """Estrae l'oggetto utile dall'output grezzo del workflow AO."""
    if isinstance(raw_output, str):
        raw_output = json.loads(raw_output)
    for node_name, node_data in raw_output.items():
        main = node_data.get("main", [])
        if main and main[0]:
            return main[0][0].get("json", {})
    return raw_output


# ── Risoluzione agent ──────────────────────────────────────────────

def list_agents():
    """Lista tutti gli agenti disponibili."""
    cfg = _get_config()
    r = requests.get(f"{cfg['base_url']}/v1/agent", headers=_headers(), timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json().get("agents", [])


def get_agent_id_by_name(agent_name):
    """Ottiene l'agentId dal nome dell'agent."""
    cfg = _get_config()
    r = requests.post(
        f"{cfg['base_url']}/v1/agent/get-agent-id-by-name",
        headers=_headers(),
        json={"agentName": agent_name},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["agentId"]


# ── Esecuzione agent ───────────────────────────────────────────────

def run_agent(agent_id, input_json, binary=None, team_id=None):
    """Avvia un agent in modalita sincrona, restituisce {taskId, status}."""
    cfg = _get_config()
    node_item = {"json": input_json}
    if binary:
        node_item["binary"] = binary
    payload = {
        "teamId": team_id or cfg['team_id'],
        "stream": False,
        "input": [node_item],
    }
    url = f"{cfg['base_url']}/v1/agent/{agent_id}/run"
    logger.info(f"AO run_agent: POST {url} | type={input_json.get('type')} practiceId={input_json.get('practiceId')} files={len(binary or {})}")
    try:
        r = requests.post(url, headers=_headers(), json=payload, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        logger.info(f"AO run_agent: taskId={data.get('taskId')} status={data.get('status')}")
        return data
    except requests.exceptions.Timeout as e:
        logger.error(f"AO run_agent TIMEOUT: POST {url} timeout={_TIMEOUT}s | {e}")
        raise
    except requests.exceptions.ConnectionError as e:
        logger.error(f"AO run_agent CONNECTION_ERROR: POST {url} | {e}")
        raise
    except requests.exceptions.HTTPError as e:
        logger.error(f"AO run_agent HTTP_ERROR: POST {url} status={e.response.status_code if e.response else '?'} body={e.response.text[:500] if e.response else '?'}")
        raise


def run_agent_stream(agent_id, input_json, binary=None, team_id=None):
    """Avvia un agent con stream SSE. Yield di ogni evento come dict."""
    cfg = _get_config()
    node_item = {"json": input_json}
    if binary:
        node_item["binary"] = binary
    payload = {
        "teamId": team_id or cfg['team_id'],
        "stream": True,
        "input": [node_item],
    }
    r = requests.post(
        f"{cfg['base_url']}/v1/agent/{agent_id}/run",
        headers=_headers(accept="text/event-stream"),
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
                yield msg
            except (json.JSONDecodeError, KeyError):
                continue


def practice_process_stream(agent_id, practice_id, files=None, team_id=None):
    """Processa una pratica in streaming. Yield di ogni evento SSE."""
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
    yield from run_agent_stream(
        agent_id,
        {"type": "processLocal", "practiceId": practice_id},
        binary=binary,
        team_id=team_id,
    )


# ── Polling task ───────────────────────────────────────────────────

def get_task_status(task_id):
    """Controlla lo stato di un task."""
    cfg = _get_config()
    url = f"{cfg['base_url']}/v1/task/{task_id}/status"
    try:
        r = requests.get(url, headers=_headers(), timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("output"):
            data["output"] = _extract_useful_output(data["output"])
        return data
    except requests.exceptions.Timeout as e:
        logger.error(f"AO get_task_status TIMEOUT: GET {url} timeout={_TIMEOUT}s | taskId={task_id}")
        raise
    except requests.exceptions.ConnectionError as e:
        logger.error(f"AO get_task_status CONNECTION_ERROR: GET {url} | taskId={task_id} | {e}")
        raise


def poll_task(task_id, interval=2.0, max_wait=120.0):
    """Polling di un task fino a completamento o timeout."""
    elapsed = 0.0
    poll_errors = 0
    logger.info(f"AO poll_task: taskId={task_id} max_wait={max_wait}s")
    while elapsed < max_wait:
        try:
            result = get_task_status(task_id)
            poll_errors = 0  # reset su successo
            if result["status"] == "COMPLETED":
                logger.info(f"AO poll_task: taskId={task_id} COMPLETED after {elapsed:.0f}s")
                return result
            if result["status"] == "FAILED":
                error_msg = result.get('error', 'unknown')
                logger.error(f"AO poll_task: taskId={task_id} FAILED after {elapsed:.0f}s | error={error_msg}")
                return result
        except Exception as e:
            poll_errors += 1
            if poll_errors >= 3:
                logger.error(f"AO poll_task: taskId={task_id} | {poll_errors} consecutive poll errors, aborting | last={e}")
                raise
            logger.warning(f"AO poll_task: taskId={task_id} | poll error {poll_errors}/3 (will retry) | {e}")
        time.sleep(interval)
        elapsed += interval
    logger.error(f"AO poll_task: taskId={task_id} TIMEOUT after {max_wait}s")
    return {"status": "TIMEOUT", "error": f"Task {task_id} non completato entro {max_wait}s"}


# ── Practice Management ───────────────────────────────────────────

def practice_info(agent_id, practice_id, team_id=None):
    """Ottiene le info di una pratica."""
    result = run_agent(agent_id, {"type": "info", "practiceId": practice_id}, team_id=team_id)
    return poll_task(result["taskId"])


def practice_process(agent_id, practice_id, files=None, team_id=None):
    """Processa una pratica (identify + extract). files: {key: (content_bytes, mime, filename)}"""
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
    result = run_agent(
        agent_id,
        {"type": "processLocal", "practiceId": practice_id},
        binary=binary,
        team_id=team_id,
    )
    return poll_task(result["taskId"], max_wait=180.0)


def practice_save(agent_id, practice_id, edited_files=None, system_facts=None, files=None, team_id=None):
    """Salva modifiche manuali e/o nuovi file su una pratica."""
    input_json = {"type": "save", "practiceId": practice_id}
    if edited_files:
        input_json["edited_files"] = edited_files
    if system_facts:
        input_json["system_facts"] = system_facts
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
    result = run_agent(agent_id, input_json, binary=binary, team_id=team_id)
    return poll_task(result["taskId"])


def practice_get_catalog(agent_id, team_id=None):
    """Ottiene il catalogo documentale di un agent."""
    result = run_agent(agent_id, {"type": "getCatalog"}, team_id=team_id)
    return poll_task(result["taskId"])


def practice_update_catalog(agent_id, catalog, team_id=None):
    """Aggiorna il catalogo documentale di un agent."""
    result = run_agent(agent_id, {"type": "updateCatalog", "catalog": catalog}, team_id=team_id)
    return poll_task(result["taskId"])


def practice_delete_file(agent_id, practice_id, content_hash, team_id=None):
    """Elimina un file da una pratica."""
    result = run_agent(
        agent_id,
        {"type": "deleteFile", "practiceId": practice_id, "contentHash": content_hash},
        team_id=team_id,
    )
    return poll_task(result["taskId"])


def practice_reprocess_file(agent_id, practice_id, content_hash, team_id=None):
    """Rielabora un singolo file di una pratica."""
    result = run_agent(
        agent_id,
        {"type": "reprocessFile", "practiceId": practice_id, "contentHash": content_hash},
        team_id=team_id,
    )
    return poll_task(result["taskId"], max_wait=180.0)


# ── Post-Stipula Sintesi ──────────────────────────────────────────

def sintesi_generate(agent_id, prompt, file_content, file_mime, file_name,
                     document_type_id=None, document_type_label=None,
                     model="gemini-2.5-flash", team_id=None):
    """Genera una sintesi di un documento notarile."""
    input_json = {"mode": "generate", "prompt": prompt, "model": model}
    if document_type_id:
        input_json["documentTypeId"] = document_type_id
    if document_type_label:
        input_json["documentTypeLabel"] = document_type_label
    ext = Path(file_name).suffix.lstrip(".")
    binary = {
        "file_1": {
            "data": base64.b64encode(file_content).decode(),
            "mimeType": file_mime,
            "fileName": file_name,
            "fileExtension": ext,
        }
    }
    result = run_agent(agent_id, input_json, binary=binary, team_id=team_id)
    return poll_task(result["taskId"], max_wait=180.0)


def sintesi_assist(agent_id, draft_prompt, action="improve", model="gpt-4o-mini", team_id=None):
    """Migliora un prompt per la sintesi."""
    input_json = {
        "mode": "assist",
        "draftPrompt": draft_prompt,
        "action": action,
        "model": model,
    }
    result = run_agent(agent_id, input_json, team_id=team_id)
    return poll_task(result["taskId"])
