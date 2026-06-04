"""Parser testo visura catastale — estrae dati strutturati dal PDF text."""

import re
import logging

logger = logging.getLogger(__name__)


def parse_visura_text(text):
    """Parsa il testo estratto da un PDF di visura catastale.

    Restituisce dict con i campi estratti (chiavi lowercase).
    Cerca: intestatario corrente (nome, CF, diritto), dati derivanti da,
    indirizzo, classamento, stato immobile (soppresso/attivo).
    """
    if not text or not text.strip():
        return {}

    result = {}
    text_norm = text.replace('\r\n', '\n').replace('\r', '\n')

    # ── Stato immobile: soppresso? ──
    m_soppr = re.search(r"immobiliare\s+soppress[ao]\s+dal\s+(\d{2}/\d{2}/\d{4})", text_norm, re.IGNORECASE)
    if m_soppr:
        result['stato_immobile'] = f"SOPPRESSO dal {m_soppr.group(1)}"

    # ── Intestatario corrente (primo nella sezione "Situazione degli intestati") ──
    # Pattern: COGNOME Nome nato/a a LUOGO (PR) il GG/MM/AAAA  CODICEFISCALE  (1) Diritto quota
    intestati_section = re.search(
        r"intestazione alla data della richiesta|situazione degli intestati dal",
        text_norm, re.IGNORECASE)

    if intestati_section:
        after = text_norm[intestati_section.end():]

        # Cerca CF (16 char alfanumerico) come anchor
        cf_matches = re.findall(
            r'([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])\*?',
            after[:1500])

        if cf_matches:
            result['codice_fiscale_intestatario'] = cf_matches[0]

            # Cerca il nominativo prima del CF
            cf_pos = after.find(cf_matches[0])
            before_cf = after[:cf_pos] if cf_pos > 0 else ''

            # Pattern: N. COGNOME Nome nato/a a LUOGO (PR) il DD/MM/YYYY
            m_nom = re.search(
                r'\d\s+([A-Z][A-Z\s]+?)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+nat[oa]\s+a\s+(.+?)\s+il\s+(\d{2}/\d{2}/\d{4})',
                before_cf)
            if m_nom:
                cognome = m_nom.group(1).strip()
                nome = m_nom.group(2).strip()
                result['intestatario'] = f"{cognome} {nome}"
                result['luogo_nascita_intestatario'] = m_nom.group(3).strip()
                result['data_nascita_intestatario'] = m_nom.group(4)
            else:
                # Fallback: prendi tutto prima del CF come nominativo (persona giuridica)
                # Es: "CERIBELLI GIUSEPPE S.R.L. COSTRUZIONI EDILI sede in BERGAMO (BG)"
                m_pj = re.search(r'\d\s+(.+?)(?:\s+sede\s+in|\s+con\s+sede)', before_cf, re.IGNORECASE)
                if m_pj:
                    result['intestatario'] = m_pj.group(1).strip()
                elif before_cf.strip():
                    # Ultimo fallback: prima riga non vuota
                    lines = [l.strip() for l in before_cf.strip().split('\n') if l.strip()]
                    if lines:
                        # Rimuovi numerazione iniziale
                        last = re.sub(r'^\d+\s+', '', lines[-1])
                        result['intestatario'] = last[:80]

        # Diritto e quota
        m_dir = re.search(r"\(\d+\)\s+(Propriet[aà]['\s]*)\s*(\d+/\d+)", after[:1500], re.IGNORECASE)
        if m_dir:
            result['diritto'] = 'Proprietà'
            result['quota'] = m_dir.group(2)
        else:
            m_dir2 = re.search(r"\(\d+\)\s+(\w[\w\s']*?)\s+(\d+/\d+)", after[:1500])
            if m_dir2:
                result['diritto'] = m_dir2.group(1).strip()
                result['quota'] = m_dir2.group(2)

        # Dati derivanti da (provenance)
        m_der = re.search(
            r"DATI\s+DERIVANTI\s+DA\s+(.+?)(?:\n\s*\n|\nSituazione|\nVisura|\nFine)",
            after[:2000], re.IGNORECASE | re.DOTALL)
        if m_der:
            derivanti = re.sub(r'\s+', ' ', m_der.group(1)).strip()
            result['dati_derivanti_da'] = derivanti[:300]

            # Estrai dettagli dall'atto
            m_atto = re.search(r"Atto\s+del\s+(\d{2}/\d{2}/\d{4})", derivanti, re.IGNORECASE)
            if m_atto:
                result['data_atto_provenienza'] = m_atto.group(1)

            m_notaio = re.search(r"Pubblico\s+ufficiale\s+([A-Z][A-Z\s]+?)(?:\s+Sede|\s+Rep)", derivanti, re.IGNORECASE)
            if m_notaio:
                result['notaio_provenienza'] = m_notaio.group(1).strip()

            m_rep = re.search(r"Repertorio\s+n\.\s*(\d+)", derivanti, re.IGNORECASE)
            if m_rep:
                result['repertorio_provenienza'] = m_rep.group(1)

            m_tipo = re.search(r"-\s*(COMPRAVENDITA|SUCCESSIONE|DONAZIONE|DECRETO|SENTENZA|DIVISIONE|PERMUTA)", derivanti, re.IGNORECASE)
            if m_tipo:
                result['tipo_atto_provenienza'] = m_tipo.group(1).upper()

    # ── Indirizzo ──
    m_ind = re.search(r"Indirizzo\s+(VIA|VIALE|PIAZZA|CORSO|VICOLO|LARGO|STRADA|PIAZZALE|CONTRADA|LOC\.|LOCALITA)\s+.+",
                       text_norm, re.IGNORECASE)
    if m_ind:
        indirizzo = m_ind.group(0).replace('Indirizzo', '').strip()
        # Rimuovi parti dopo "Notifica" o "Partita"
        indirizzo = re.split(r'\s*(?:Notifica|Partita|Annotazioni)', indirizzo)[0].strip()
        if indirizzo:
            result['indirizzo'] = indirizzo

    # ── Classamento (dalla sezione più recente con dati) ──
    # Pattern: Categoria Classe Consistenza Superficie Rendita
    m_class = re.search(
        r'([A-Z]/\d+)\s+(\d+)\s+(\d+(?:,\d+)?\s*(?:vani|m[²2]))\s+(?:Totale:\s*)?(\d+(?:,\d+)?\s*m[²2])\s+Euro\s+([\d.,]+)',
        text_norm)
    if m_class:
        result['categoria'] = m_class.group(1)
        result['classe'] = m_class.group(2)
        result['consistenza'] = m_class.group(3).strip()
        result['superficie'] = m_class.group(4).strip()
        result['rendita'] = f"€ {m_class.group(5)}"

    # ── Variazioni rilevate (info, non cambiano F/M/S) ──
    _INFO_VARIATIONS = [
        ('variazione toponomastica', 'Variazione toponomastica'),
        ('variazione di classamento', 'Variazione di classamento'),
        ('variazione di consistenza', 'Variazione di consistenza'),
        ('variazione della rendita', 'Variazione della rendita'),
        ('variazione colturale', 'Variazione colturale'),
        ('ultimazione di fabbricato', 'Ultimazione di fabbricato urbano'),
    ]
    text_lower = text_norm.lower()
    variazioni = []
    for pattern, label in _INFO_VARIATIONS:
        if pattern in text_lower:
            variazioni.append(label)
    if variazioni:
        result['variazioni_non_rilevanti'] = '; '.join(variazioni)

    logger.info(f"Visura parser: estratti {len(result)} campi: {list(result.keys())}")
    return result
