"""Servizio generazione PDF elegante per sintesi documenti."""

import re
from io import BytesIO
from fpdf import FPDF


class SintesiPDF(FPDF):
    """PDF con header/footer stilizzati per sintesi documentali."""

    BROWN = (121, 85, 61)
    DARK = (45, 45, 45)
    WARM_BG = (252, 249, 245)
    ACCENT = (166, 124, 82)
    MUTED = (150, 140, 130)
    TABLE_HEAD_BG = (121, 85, 61)
    TABLE_HEAD_FG = (255, 255, 255)
    TABLE_ROW_EVEN = (250, 247, 243)
    TABLE_ROW_ODD = (255, 255, 255)
    TABLE_BORDER = (210, 200, 185)

    def __init__(self, title="Sintesi documento"):
        super().__init__()
        self._doc_title = title
        self.set_auto_page_break(auto=True, margin=25)

    def header(self):
        # Barra top
        self.set_fill_color(*self.BROWN)
        self.rect(0, 0, 210, 3.5, 'F')
        # Titolo centrato
        self.set_y(14)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*self.BROWN)
        self.cell(0, 10, self._doc_title, align="C", new_x="LMARGIN", new_y="NEXT")
        # Linea decorativa
        self.set_draw_color(*self.ACCENT)
        self.set_line_width(0.5)
        y = self.get_y() + 2
        self.line(60, y, 150, y)
        self.ln(10)

    def footer(self):
        self.set_y(-16)
        self.set_draw_color(*self.TABLE_BORDER)
        self.set_line_width(0.3)
        self.line(30, self.get_y(), 180, self.get_y())
        self.ln(3)
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(*self.MUTED)
        self.cell(0, 8, f"Saba Workflow  |  Pagina {self.page_no()}/{{nb}}", align="C")


def _strip_md(text):
    """Rimuove marcatori markdown **bold** e *italic*."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    return text.strip()


def _parse_sintesi(text):
    """Parsa il testo sintesi in sezioni strutturate.

    Formato atteso dall'AI:
      Intro opzionale. 1. **Sezione** - **Chiave:** Valore - **Chiave:** Valore. 2. **Sezione** ...
    Oppure formato con newline.

    Returns: lista di (section_title, [(key, value), ...])
    """
    # Normalizza: se è tutto su una riga, splitta su numbered sections
    # Pattern: " 1. **Titolo**" oppure "\n1. **Titolo**"
    # Prima splitta il testo in segmenti per sezione numerata
    section_pattern = r'(?:^|\s)(\d+)\.\s+\*\*([^*]+)\*\*'

    # Trova tutte le sezioni numerate
    matches = list(re.finditer(section_pattern, text))

    sections = []

    # Testo prima della prima sezione (intro)
    if matches:
        intro_text = text[:matches[0].start()].strip()
        if intro_text:
            intro_text = _strip_md(re.sub(r'^Sintesi\s+Atto\s+Notarile\s*', '', intro_text).strip())
            if intro_text:
                sections.append(('intro', intro_text, []))
    else:
        # Nessuna sezione numerata — prova a parsare come lista key:value
        pairs = _extract_kv_pairs(text)
        if pairs:
            sections.append(('', '', pairs))
        else:
            sections.append(('intro', _strip_md(text), []))
        return sections

    for idx, match in enumerate(matches):
        section_title = _strip_md(match.group(2))
        # Contenuto tra questa sezione e la prossima
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        pairs = _extract_kv_pairs(content)
        sections.append(('section', section_title, pairs))

    return sections


def _extract_kv_pairs(text):
    """Estrae coppie chiave-valore da testo con pattern **Key:** Value."""
    pairs = []
    # Splitta su " - " che separa i campi, ma preserva " - " dentro i valori
    # Pattern: **Chiave:** Valore
    kv_pattern = r'\*\*([^*:]+?):\*\*\s*'
    parts = re.split(kv_pattern, text)

    # parts = [before, key1, val1, key2, val2, ...]
    if len(parts) >= 3:
        for i in range(1, len(parts) - 1, 2):
            key = parts[i].strip()
            val = parts[i + 1].strip().rstrip(' -').rstrip('.')
            if not val:
                val = "—"
            pairs.append((key, val))
    elif not pairs:
        # Fallback: prova con newline
        for line in text.split('\n'):
            line = line.strip().lstrip('- ')
            m = re.match(r'\*\*(.+?):\*\*\s*(.*)', line)
            if m:
                pairs.append((m.group(1).strip(), _strip_md(m.group(2).strip()) or "—"))

    return pairs


def generate_sintesi_pdf(title, text):
    """Genera un PDF elegante con sezioni e tabelle centrate.

    Returns: bytes del PDF.
    """
    pdf = SintesiPDF(title=title)
    pdf.alias_nb_pages()
    pdf.add_page()

    sections = _parse_sintesi(text)

    # Larghezza tabella e margini per centratura
    table_w = 160
    margin_left = (210 - table_w) / 2
    col_key_w = 55
    col_val_w = table_w - col_key_w

    for stype, stitle, pairs in sections:
        if stype == 'intro':
            # Testo introduttivo centrato in corsivo
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(*SintesiPDF.MUTED)
            pdf.set_x(margin_left)
            pdf.multi_cell(table_w, 6, _strip_md(stitle), align="C")
            pdf.ln(6)
            continue

        if stitle:
            # Header sezione
            pdf.ln(4)
            pdf.set_fill_color(*SintesiPDF.TABLE_HEAD_BG)
            pdf.set_text_color(*SintesiPDF.TABLE_HEAD_FG)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_x(margin_left)
            pdf.cell(table_w, 9, f"  {stitle}", fill=True, align="L",
                     new_x="LMARGIN", new_y="NEXT")

        if not pairs:
            continue

        # Righe tabella
        for i, (key, val) in enumerate(pairs):
            bg = SintesiPDF.TABLE_ROW_EVEN if i % 2 == 0 else SintesiPDF.TABLE_ROW_ODD
            pdf.set_fill_color(*bg)
            pdf.set_draw_color(*SintesiPDF.TABLE_BORDER)

            # Calcola altezza necessaria per il valore (multi-line)
            pdf.set_font("Helvetica", "", 9)
            val_clean = _strip_md(val)
            # Stima righe necessarie
            val_lines = pdf.multi_cell(col_val_w - 4, 5.5, val_clean, dry_run=True, output="LINES")
            row_h = max(8, len(val_lines) * 5.5 + 3)

            # Check page break
            if pdf.get_y() + row_h > 272:
                pdf.add_page()

            y_start = pdf.get_y()

            # Cella chiave
            pdf.set_x(margin_left)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*SintesiPDF.BROWN)
            pdf.rect(margin_left, y_start, col_key_w, row_h, 'DF')
            pdf.set_xy(margin_left + 3, y_start + (row_h - 5.5) / 2)
            pdf.cell(col_key_w - 6, 5.5, key, align="R")

            # Cella valore
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*SintesiPDF.DARK)
            pdf.rect(margin_left + col_key_w, y_start, col_val_w, row_h, 'DF')
            pdf.set_xy(margin_left + col_key_w + 3, y_start + (row_h - len(val_lines) * 5.5) / 2)
            pdf.multi_cell(col_val_w - 6, 5.5, val_clean, align="L")

            pdf.set_y(y_start + row_h)

        pdf.ln(4)

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()
