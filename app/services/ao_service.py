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
    """Estrae l'oggetto utile dall'output grezzo del workflow AO.
    Restituisce il json del primo nodo, con eventuale binary preservato sotto _binary.
    """
    if isinstance(raw_output, str):
        raw_output = json.loads(raw_output)
    for node_name, node_data in raw_output.items():
        main = node_data.get("main", [])
        if main and main[0]:
            item = main[0][0]
            result = item.get("json", {})
            # Preserva binary output (es. PDF da sister-agent)
            if item.get("binary"):
                # Log struttura binary per debug
                _bin = item["binary"]
                if isinstance(_bin, dict):
                    for _bk, _bv in _bin.items():
                        if isinstance(_bv, dict):
                            _data_len = len(str(_bv.get('data', ''))) if _bv.get('data') else 0
                            logger.info(f"AO raw binary[{_bk}]: data_len={_data_len}, "
                                        f"s3Stored={_bv.get('s3Stored')}, "
                                        f"fileName={_bv.get('fileName')}, "
                                        f"fileSize={_bv.get('fileSize')}")
                if isinstance(result, dict):
                    result["_binary"] = item["binary"]
                else:
                    result = {"_json": result, "_binary": item["binary"]}
            return result
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


# ── Download binari S3 ────────────────────────────────────────────

def download_s3_binary(content_hash):
    """Scarica un file binario da AO tramite contentHash (file su S3).
    Prova endpoint comuni dell'API AO. Restituisce bytes o None.
    """
    cfg = _get_config()
    base = cfg['base_url']
    headers = _headers(accept="application/octet-stream")

    # Prova gli endpoint possibili per download file
    endpoints = [
        f"{base}/v1/file/{content_hash}/download",
        f"{base}/v1/file/{content_hash}",
        f"{base}/v1/binary/{content_hash}",
    ]
    for url in endpoints:
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 200 and len(r.content) > 100:
                logger.info(f"AO download_s3_binary: OK da {url} ({len(r.content)} bytes)")
                return r.content
            elif r.status_code == 404:
                continue
            else:
                logger.debug(f"AO download_s3_binary: {url} status={r.status_code} size={len(r.content)}")
        except Exception as e:
            logger.debug(f"AO download_s3_binary: {url} error: {e}")
            continue

    logger.warning(f"AO download_s3_binary: nessun endpoint funzionante per contentHash={content_hash[:16]}...")
    return None


# ── Polling task ───────────────────────────────────────────────────

def get_task_status(task_id, hydrate_binaries=True):
    """Controlla lo stato di un task."""
    cfg = _get_config()
    url = f"{cfg['base_url']}/v1/task/{task_id}/status"
    if hydrate_binaries:
        url += "?hydrateBinaries=true"
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


def cancel_task(task_id):
    """Tenta di cancellare un task AO in esecuzione."""
    cfg = _get_config()
    url = f"{cfg['base_url']}/v1/task/{task_id}/cancel"
    try:
        r = requests.post(url, headers=_headers(), timeout=10)
        logger.info(f"AO cancel_task: taskId={task_id} status_code={r.status_code}")
        return r.status_code < 400
    except Exception as e:
        logger.warning(f"AO cancel_task: taskId={task_id} failed: {e}")
        return False


def poll_task(task_id, interval=2.0, max_wait=120.0, stop_event=None, hydrate_binaries=True):
    """Polling di un task fino a completamento o timeout.
    Se stop_event è fornito e viene settato, interrompe il polling immediatamente.
    """
    elapsed = 0.0
    poll_errors = 0
    logger.info(f"AO poll_task: taskId={task_id} max_wait={max_wait}s")
    while elapsed < max_wait:
        # Check stop_event prima di ogni poll
        if stop_event and stop_event.is_set():
            logger.info(f"AO poll_task: taskId={task_id} CANCELLED by stop_event after {elapsed:.0f}s")
            cancel_task(task_id)
            return {"status": "CANCELLED", "error": "Interrotto dall'utente"}
        try:
            result = get_task_status(task_id, hydrate_binaries=hydrate_binaries)
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
        # Sleep breve frazionato per reagire subito allo stop_event
        _slept = 0.0
        while _slept < interval:
            if stop_event and stop_event.is_set():
                break
            time.sleep(min(0.5, interval - _slept))
            _slept += 0.5
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

def sintesi_generate(agent_id, prompt, file_content=None, file_mime=None, file_name=None,
                     document_type_id=None, document_type_label=None,
                     ocr_text=None, model="gemini-2.5-flash", team_id=None):
    """Genera una sintesi di un documento notarile.
    Se ocr_text è fornito, lo invia come testo (più veloce).
    Altrimenti invia il file binario.
    """
    input_json = {"mode": "generate", "prompt": prompt, "model": model}
    if document_type_id:
        input_json["documentTypeId"] = document_type_id
    if document_type_label:
        input_json["documentTypeLabel"] = document_type_label

    binary = None
    if ocr_text:
        # Passa il testo OCR direttamente — molto più veloce
        input_json["ocrText"] = ocr_text
    elif file_content:
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
