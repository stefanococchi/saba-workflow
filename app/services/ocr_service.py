"""Google Document AI OCR service — estrae testo e coordinate da PDF/immagini."""

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


def _extract_word_boxes(doc, page_offset=0):
    """Estrae bounding box per ogni parola (token) dal documento.

    Returns lista di {page, text, bbox: {x, y, w, h}} con coordinate normalizzate (0-1).
    Le coordinate sono nello spazio di Document AI (eventualmente raddrizzato).
    """
    words = []
    for page_idx, page in enumerate(doc.pages):
        for token in page.tokens:
            if not token.layout or not token.layout.bounding_poly:
                continue

            # Testo del token
            text = ""
            if token.layout.text_anchor and token.layout.text_anchor.text_segments:
                for seg in token.layout.text_anchor.text_segments:
                    start = seg.start_index
                    end = seg.end_index
                    text += doc.text[start:end]
            text = text.strip()
            if not text:
                continue

            # Coordinate normalizzate (0-1)
            nv = token.layout.bounding_poly.normalized_vertices
            if nv and len(nv) >= 4:
                x_min = min(v.x for v in nv)
                y_min = min(v.y for v in nv)
                x_max = max(v.x for v in nv)
                y_max = max(v.y for v in nv)
            elif token.layout.bounding_poly.vertices and page.dimension:
                verts = token.layout.bounding_poly.vertices
                pw = page.dimension.width or 1
                ph = page.dimension.height or 1
                x_min = min(v.x / pw for v in verts)
                y_min = min(v.y / ph for v in verts)
                x_max = max(v.x / pw for v in verts)
                y_max = max(v.y / ph for v in verts)
            else:
                continue

            words.append({
                "p": page_offset + page_idx,
                "t": text,
                "x": round(x_min, 4),
                "y": round(y_min, 4),
                "w": round(x_max - x_min, 4),
                "h": round(y_max - y_min, 4),
            })
    return words


def _extract_page_dims(doc, page_offset=0):
    """Estrae dimensioni pagina come viste da Document AI (post-rotazione).

    Returns dict {page_index: {w, h}} con dimensioni in punti.
    """
    dims = {}
    for page_idx, page in enumerate(doc.pages):
        if page.dimension:
            dims[page_offset + page_idx] = {
                "w": round(page.dimension.width or 0, 1),
                "h": round(page.dimension.height or 0, 1),
            }
    return dims


def _process_single(client, resource_name, documentai, file_bytes, mime_type):
    """Processa un singolo documento e restituisce (text, pages, confidences, words, page_dims)."""
    raw_document = documentai.RawDocument(content=file_bytes, mime_type=mime_type)
    request = documentai.ProcessRequest(name=resource_name, raw_document=raw_document)
    result = client.process_document(request=request)
    doc = result.document

    confidences = []
    for page in doc.pages:
        for block in page.blocks:
            if block.layout and block.layout.confidence:
                confidences.append(block.layout.confidence)

    words = _extract_word_boxes(doc)
    page_dims = _extract_page_dims(doc)

    return doc.text, len(doc.pages), confidences, words, page_dims


def extract_text(file_bytes: bytes, mime_type: str = "application/pdf") -> dict:
    """Estrae testo e coordinate parole da un file usando Google Document AI.

    Per PDF con più di 15 pagine, divide automaticamente in chunk
    e unisce i risultati.

    Returns:
        {
            "text": str,           # testo completo
            "pages": int,          # numero pagine
            "confidence": float,   # confidenza media (0-1)
            "words": list,         # [{p, t, x, y, w, h}, ...] coordinate normalizzate
            "error": str | None,
        }
    """
    if not is_configured():
        return {"text": "", "pages": 0, "confidence": 0, "words": [], "error": "Document AI non configurato"}

    try:
        from google.cloud import documentai_v1 as documentai
    except ImportError:
        return {"text": "", "pages": 0, "confidence": 0, "words": [], "error": "google-cloud-documentai non installato"}

    try:
        client, resource_name, documentai = _make_client()

        # Controlla se serve split (solo per PDF)
        needs_split = False
        if mime_type == "application/pdf":
            page_count = _count_pdf_pages(file_bytes)
            needs_split = page_count > _MAX_PAGES_PER_REQUEST

        if not needs_split:
            text, pages, confidences, words, page_dims = _process_single(
                client, resource_name, documentai, file_bytes, mime_type
            )
        else:
            logger.info(f"PDF con {page_count} pagine — split in chunk da {_MAX_PAGES_PER_REQUEST}")
            chunks = _split_pdf(file_bytes, _MAX_PAGES_PER_REQUEST)
            all_text = []
            pages = 0
            confidences = []
            words = []
            page_dims = {}

            for i, chunk_bytes in enumerate(chunks):
                logger.info(f"OCR chunk {i + 1}/{len(chunks)}...")
                chunk_text, chunk_pages, chunk_confs, chunk_words, chunk_dims = _process_single(
                    client, resource_name, documentai, chunk_bytes, mime_type
                )
                # Offset page numbers per chunk
                for w in chunk_words:
                    w["p"] += pages
                offset_dims = {pages + k: v for k, v in chunk_dims.items()}
                all_text.append(chunk_text)
                pages += chunk_pages
                confidences.extend(chunk_confs)
                words.extend(chunk_words)
                page_dims.update(offset_dims)

            text = "\n".join(all_text)

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        logger.info(f"OCR completato: {pages} pagine, {len(text)} chars, {len(words)} parole, confidence={avg_confidence:.2f}")

        return {
            "text": text,
            "pages": pages,
            "confidence": round(avg_confidence, 3),
            "words": words,
            "page_dims": page_dims,
            "error": None,
        }

    except Exception as e:
        logger.error(f"OCR error: {e}")
        return {"text": "", "pages": 0, "confidence": 0, "words": [], "error": str(e)}
