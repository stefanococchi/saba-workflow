"""Parser per PDF Ispezione Ipotecaria SISTER (nativi, non scansionati)."""

import re
from io import BytesIO
from pypdf import PdfReader


def parse_ipotecaria_pdf(pdf_bytes):
    """Parsa un PDF di ispezione ipotecaria SISTER e restituisce dati strutturati.

    Args:
        pdf_bytes: bytes del PDF

    Returns:
        dict con: header, soggetto, formalita[]
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    text = ''
    for page in reader.pages:
        t = page.extract_text() or ''
        # Rimuovi header ripetuto su ogni pagina (dopo "Richiedente ...")
        t = re.sub(
            r'Ispezione Ipotecaria\nDirezione Provinciale.*?Richiedente \w+\n',
            '', t, flags=re.DOTALL
        )
        text += t + '\n'

    result = {
        'header': _parse_header(text),
        'soggetto': _parse_soggetto(text),
        'formalita': _parse_formalita(text),
    }
    return result


def _parse_header(text):
    """Estrae dati dell'intestazione."""
    header = {}

    m = re.search(r'Direzione Provinciale di (.+?)[\s]+Data', text)
    if m:
        header['direzione'] = m.group(1).strip()

    m = re.search(r'Data (\d{2}/\d{2}/\d{4}) Ora ([\d:]+)', text)
    if m:
        header['data'] = m.group(1)
        header['ora'] = m.group(2)

    m = re.search(r'Ispezione n\. (\S+) del (\d{2}/\d{2}/\d{4})', text)
    if m:
        header['numero_ispezione'] = m.group(1)
        header['data_ispezione'] = m.group(2)

    m = re.search(r'Codice fiscale:\s*(\S+)', text)
    if m:
        header['codice_fiscale'] = m.group(1).split(' ')[0]

    m = re.search(r'Periodo informatizzato dal\s+(\S+)\s+al\s+(\S+)', text)
    if m:
        header['periodo_informatizzato'] = f"{m.group(1)} - {m.group(2)}"

    m = re.search(r'Periodo recuperato e validato dal\s+(\S+)\s+al\s+(\S+)', text)
    if m:
        header['periodo_recuperato'] = f"{m.group(1)} - {m.group(2)}"

    return header


def _parse_soggetto(text):
    """Estrae dati del soggetto dall'elenco omonimi."""
    soggetto = {}

    m = re.search(r'Elenco omonimi\n\d+\.\s+(.+?)\n', text)
    if m:
        soggetto['nominativo'] = m.group(1).strip()

    m = re.search(r'Luogo di nascita\s+(.+?)(?:\n|$)', text)
    if m:
        soggetto['luogo_nascita'] = m.group(1).strip()

    m = re.search(r'Data di nascita\s+(\S+)', text)
    if m:
        soggetto['data_nascita'] = m.group(1)

    m = re.search(r'Codice fiscale\s+(\S+)', text)
    if m:
        cf = m.group(1).rstrip('*').strip()
        soggetto['codice_fiscale'] = cf

    return soggetto


def _parse_formalita(text):
    """Estrae l'elenco delle formalità strutturate."""
    formalita = []

    # Pattern per l'inizio di ogni formalità: "N. TIPO del DD/MM/YYYY - Registro Particolare NNNN Registro Generale NNNN"
    pattern = re.compile(
        r'(\d+)\.\s+'
        r'(TRASCRIZIONE\s+(?:A FAVORE|CONTRO|A FAVORE E CONTRO)|ISCRIZIONE\s+(?:A FAVORE|CONTRO))\s+'
        r'del\s+(\d{2}/\d{2}/\d{4})\s*-\s*'
        r'Registro Particolare\s+(\d+)\s+'
        r'Registro Generale\s+(\d+)'
    )

    # Trova tutte le formalità
    matches = list(pattern.finditer(text))

    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end].strip()

        f = {
            'numero': int(match.group(1)),
            'tipo_formalita': match.group(2).strip(),
            'data': match.group(3),
            'registro_particolare': match.group(4),
            'registro_generale': match.group(5),
        }

        # Pubblico ufficiale e repertorio
        m = re.search(
            r'Pubblico ufficiale\s+(.+?)\s+Repertorio\s+(\S+)\s+del\s+(\d{2}/\d{2}/\d{4})',
            block
        )
        if m:
            f['pubblico_ufficiale'] = m.group(1).strip()
            f['repertorio'] = m.group(2)
            f['data_repertorio'] = m.group(3)

        # Specie atto e descrizione (es. "ATTO TRA VIVI - COMPRAVENDITA" o "IPOTECA VOLONTARIA derivante da ...")
        m = re.search(
            r'(ATTO TRA VIVI|ATTO PER CAUSA DI MORTE|IPOTECA VOLONTARIA)\s*[-–]\s*(.+?)(?:\n|$)',
            block
        )
        if m:
            f['specie_atto'] = m.group(1).strip()
            f['descrizione'] = m.group(2).strip()
        else:
            # Fallback: "IPOTECA VOLONTARIA derivante da ..."
            m = re.search(r'(IPOTECA VOLONTARIA)\s+derivante da\s+(.+?)(?:\n|$)', block)
            if m:
                f['specie_atto'] = m.group(1)
                f['descrizione'] = m.group(2).strip()

        # Ubicazione immobili
        m = re.search(r'Immobili siti in\s+(.+?)(?:\n|$)', block)
        if m:
            f['ubicazione'] = m.group(1).strip()

        # Qualifica soggetto
        m = re.search(r'SOGGETTO\s+(ACQUIRENTE|VENDITORE|DEBITORE|CREDITORE)', block)
        if m:
            f['qualifica'] = f'SOGGETTO {m.group(1)}'

        # Nota formato
        if 'formato immagine' in block:
            f['nota_formato'] = 'immagine'
        elif 'formato elettronico' in block:
            f['nota_formato'] = 'elettronico'
        if 'Presenza Titolo Telematico' in block:
            f['titolo_telematico'] = True

        # Documenti successivi correlati (cancellazioni, etc.)
        doc_match = re.search(r'Documenti successivi correlati:\n(.+?)(?=\n\d+\.\s+[A-Z]|\Z)', block, re.DOTALL)
        if doc_match:
            doc_text = doc_match.group(1).strip()
            f['documenti_correlati'] = doc_text
            # Cerca info cancellazione
            canc = re.search(r'Cancellazione\s+(totale|parziale)\s+eseguita in data\s+(\S+)', doc_text)
            if canc:
                f['cancellazione'] = {
                    'tipo': canc.group(1),
                    'data': canc.group(2),
                }
            estinz = re.search(r'estinzione\s+(totale|parziale)\s+.*?avvenuta in data\s*\n?\s*(\S+)', doc_text)
            if estinz:
                f['estinzione'] = {
                    'tipo': estinz.group(1),
                    'data': estinz.group(2),
                }

        formalita.append(f)

    return formalita
