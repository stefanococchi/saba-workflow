"""Google Document AI OCR service — estrae testo da PDF/immagini."""

import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

_MAX_PAGES_PER_REQUEST = 15


def _cfg(key, default=""):
    """Legge env var in modo lazy (dopo load_dotenv)."""
    return os.getenv(key, default)


def _ensure_credentials():
    """Gestisce credenziali Google sia da file che da JSON inline (per Railway/prod).

    - GOOGLE_APPLICATION_CREDENTIALS punta a un file → nessuna azione
    - GOOGLE_CREDENTIALS_JSON contiene il JSON inline → scrive un file temporaneo
      e imposta GOOGLE_APPLICATION_CREDENTIALS
    """
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        return
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        return
    try:
        creds = json.loads(creds_json)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(creds, tmp)
        tmp.close()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name
        logger.info(f"Credenziali Google scritte da GOOGLE_CREDENTIALS_JSON → {tmp.name}")
    except Exception as e:
        logger.error(f"Errore parsing GOOGLE_CREDENTIALS_JSON: {e}")


# Inizializza credenziali all'import del modulo
_ensure_credentials()


def is_configured():
    """True se le variabili Google Document AI sono impostate."""
    has_creds = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GOOGLE_CREDENTIALS_JSON"))
    return bool(_cfg("GOOGLE_CLOUD_PROJECT") and _cfg("DOCUMENTAI_PROCESSOR_ID") and has_creds)


def _count_pdf_pages(file_bytes: bytes) -> int:
    """Conta le pagine di un PDF senza dipendenze esterne."""
    try:
        import pypdf
        from io import BytesIO
        reader = pypdf.PdfReader(BytesIO(file_bytes))
        return len(reader.pages)
    except ImportError:
        # Fallback: conta i marker /Type /Page nel PDF raw
        import re
        return len(re.findall(rb'/Type\s*/Page(?!s)', file_bytes))
    except Exception:
        return 0


def _split_pdf(file_bytes: bytes, chunk_size: int) -> list[bytes]:
    """Divide un PDF in chunk da chunk_size pagine. Restituisce lista di bytes."""
    from io import BytesIO
    import pypdf

    reader = pypdf.PdfReader(BytesIO(file_bytes))
    total = len(reader.pages)
    chunks = []

    for start in range(0, total, chunk_size):
        writer = pypdf.PdfWriter()
        for i in range(start, min(start + chunk_size, total)):
            writer.add_page(reader.pages[i])
        buf = BytesIO()
        writer.write(buf)
        chunks.append(buf.getvalue())

    return chunks


def _make_client():
    """Crea il client Document AI con endpoint corretto per la regione."""
    from google.cloud import documentai_v1 as documentai
    from google.api_core.client_options import ClientOptions

    location = _cfg("DOCUMENTAI_LOCATION", "eu")
    opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=opts)
    resource_name = client.processor_path(
        _cfg("GOOGLE_CLOUD_PROJECT"), location, _cfg("DOCUMENTAI_PROCESSOR_ID")
    )
    return client, resource_name, documentai


def _process_single(client, resource_name, documentai, file_bytes, mime_type):
    """Processa un singolo documento e restituisce (text, pages, confidences)."""
    raw_document = documentai.RawDocument(content=file_bytes, mime_type=mime_type)
    request = documentai.ProcessRequest(name=resource_name, raw_document=raw_document)
    result = client.process_document(request=request)
    doc = result.document

    confidences = []
    for page in doc.pages:
        for block in page.blocks:
            if block.layout and block.layout.confidence:
                confidences.append(block.layout.confidence)

    return doc.text, len(doc.pages), confidences


def extract_text(file_bytes: bytes, mime_type: str = "application/pdf") -> dict:
    """Estrae testo da un file usando Google Document AI.

    Per PDF con più di 15 pagine, divide automaticamente in chunk
    e unisce i risultati.

    Returns:
        {
            "text": str,           # testo completo
            "pages": int,          # numero pagine
            "confidence": float,   # confidenza media (0-1)
            "error": str | None,
        }
    """
    if not is_configured():
        return {"text": "", "pages": 0, "confidence": 0, "error": "Document AI non configurato"}

    try:
        from google.cloud import documentai_v1 as documentai
    except ImportError:
        return {"text": "", "pages": 0, "confidence": 0, "error": "google-cloud-documentai non installato"}

    try:
        client, resource_name, documentai = _make_client()

        # Controlla se serve split (solo per PDF)
        needs_split = False
        if mime_type == "application/pdf":
            page_count = _count_pdf_pages(file_bytes)
            needs_split = page_count > _MAX_PAGES_PER_REQUEST

        if not needs_split:
            text, pages, confidences = _process_single(
                client, resource_name, documentai, file_bytes, mime_type
            )
        else:
            # Split PDF in chunk da 15 pagine
            logger.info(f"PDF con {page_count} pagine — split in chunk da {_MAX_PAGES_PER_REQUEST}")
            chunks = _split_pdf(file_bytes, _MAX_PAGES_PER_REQUEST)
            all_text = []
            pages = 0
            confidences = []

            for i, chunk_bytes in enumerate(chunks):
                logger.info(f"OCR chunk {i + 1}/{len(chunks)}...")
                chunk_text, chunk_pages, chunk_confs = _process_single(
                    client, resource_name, documentai, chunk_bytes, mime_type
                )
                all_text.append(chunk_text)
                pages += chunk_pages
                confidences.extend(chunk_confs)

            text = "\n".join(all_text)

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        logger.info(f"OCR completato: {pages} pagine, {len(text)} chars, confidence={avg_confidence:.2f}")

        return {
            "text": text,
            "pages": pages,
            "confidence": round(avg_confidence, 3),
            "error": None,
        }

    except Exception as e:
        logger.error(f"OCR error: {e}")
        return {"text": "", "pages": 0, "confidence": 0, "error": str(e)}
