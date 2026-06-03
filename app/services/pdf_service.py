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


# ── Report Pratica ──────────────────────────────────────────────


class ReportPDF(FPDF):
    """PDF report riepilogativo per pratica documentale."""

    BROWN = (121, 85, 61)
    DARK = (45, 45, 45)
    ACCENT = (166, 124, 82)
    MUTED = (150, 140, 130)
    TABLE_HEAD_BG = (121, 85, 61)
    TABLE_HEAD_FG = (255, 255, 255)
    TABLE_ROW_EVEN = (250, 247, 243)
    TABLE_ROW_ODD = (255, 255, 255)
    TABLE_BORDER = (210, 200, 185)
    GREEN = (46, 125, 50)
    RED = (198, 40, 40)
    ORANGE = (230, 145, 0)

    MARGIN = 25
    TABLE_W = 210 - 2 * 25  # 160

    def __init__(self, practice_id=''):
        super().__init__()
        self._practice_id = practice_id
        self.set_auto_page_break(auto=True, margin=25)

    def header(self):
        self.set_fill_color(*self.BROWN)
        self.rect(0, 0, 210, 3.5, 'F')
        self.set_y(10)
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(*self.BROWN)
        self.cell(0, 8, 'Report Pratica', align='C', new_x='LMARGIN', new_y='NEXT')
        self.set_draw_color(*self.ACCENT)
        self.set_line_width(0.5)
        y = self.get_y() + 1
        self.line(70, y, 140, y)
        self.ln(6)

    def footer(self):
        self.set_y(-16)
        self.set_draw_color(*self.TABLE_BORDER)
        self.set_line_width(0.3)
        self.line(30, self.get_y(), 180, self.get_y())
        self.ln(3)
        self.set_font('Helvetica', 'I', 7.5)
        self.set_text_color(*self.MUTED)
        pid = f' {self._practice_id}' if self._practice_id else ''
        self.cell(0, 8, f'Saba Workflow \u2014 Report Pratica{pid}  |  Pagina {self.page_no()}/{{nb}}', align='C')

    # ── Helpers ──

    def section_title(self, title):
        self.ln(4)
        self.set_fill_color(*self.TABLE_HEAD_BG)
        self.set_text_color(*self.TABLE_HEAD_FG)
        self.set_font('Helvetica', 'B', 10)
        self.set_x(self.MARGIN)
        self.cell(self.TABLE_W, 9, f'  {title}', fill=True, align='L',
                  new_x='LMARGIN', new_y='NEXT')

    def sub_title(self, title):
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(*self.ACCENT)
        self.set_x(self.MARGIN)
        self.cell(self.TABLE_W, 7, title, new_x='LMARGIN', new_y='NEXT')

    def kv_table(self, rows, key_w=55):
        val_w = self.TABLE_W - key_w
        for i, (key, val) in enumerate(rows):
            bg = self.TABLE_ROW_EVEN if i % 2 == 0 else self.TABLE_ROW_ODD
            self.set_fill_color(*bg)
            self.set_draw_color(*self.TABLE_BORDER)
            self.set_font('Helvetica', '', 9)
            val_str = str(val) if val else '\u2014'
            val_lines = self.multi_cell(val_w - 4, 5.5, val_str, dry_run=True, output='LINES')
            row_h = max(8, len(val_lines) * 5.5 + 3)
            if self.get_y() + row_h > 272:
                self.add_page()
            y0 = self.get_y()
            # Key
            self.set_x(self.MARGIN)
            self.set_font('Helvetica', 'B', 9)
            self.set_text_color(*self.BROWN)
            self.rect(self.MARGIN, y0, key_w, row_h, 'DF')
            self.set_xy(self.MARGIN + 3, y0 + (row_h - 5.5) / 2)
            self.cell(key_w - 6, 5.5, str(key), align='R')
            # Value
            self.set_font('Helvetica', '', 9)
            self.set_text_color(*self.DARK)
            self.rect(self.MARGIN + key_w, y0, val_w, row_h, 'DF')
            self.set_xy(self.MARGIN + key_w + 3, y0 + (row_h - len(val_lines) * 5.5) / 2)
            self.multi_cell(val_w - 6, 5.5, val_str, align='L')
            self.set_y(y0 + row_h)
        self.ln(4)

    def check_table(self, checks):
        col_label = 55
        col_tit = 40
        col_cat = 40
        col_esito = self.TABLE_W - col_label - col_tit - col_cat
        # Header
        self.set_fill_color(*self.TABLE_HEAD_BG)
        self.set_text_color(*self.TABLE_HEAD_FG)
        self.set_font('Helvetica', 'B', 8)
        self.set_x(self.MARGIN)
        self.cell(col_label, 8, '  Controllo', fill=True, border=1)
        self.cell(col_tit, 8, 'Titolo', fill=True, border=1, align='C')
        self.cell(col_cat, 8, 'Catasto/Ipot.', fill=True, border=1, align='C')
        self.cell(col_esito, 8, 'Esito', fill=True, border=1, align='C')
        self.ln()
        # Rows
        for i, c in enumerate(checks):
            bg = self.TABLE_ROW_EVEN if i % 2 == 0 else self.TABLE_ROW_ODD
            self.set_fill_color(*bg)
            self.set_draw_color(*self.TABLE_BORDER)
            vt = str(c.get('val_titolo', '\u2014'))
            vc = str(c.get('val_catasto', '\u2014'))
            self.set_font('Helvetica', '', 8)
            lt = self.multi_cell(col_tit - 4, 5, vt, dry_run=True, output='LINES')
            lc = self.multi_cell(col_cat - 4, 5, vc, dry_run=True, output='LINES')
            row_h = max(8, max(len(lt), len(lc)) * 5 + 3)
            if self.get_y() + row_h > 272:
                self.add_page()
            y0 = self.get_y()
            # Label
            self.set_x(self.MARGIN)
            self.set_font('Helvetica', 'B', 8)
            self.set_text_color(*self.DARK)
            self.rect(self.MARGIN, y0, col_label, row_h, 'DF')
            self.set_xy(self.MARGIN + 2, y0 + (row_h - 5) / 2)
            self.cell(col_label - 4, 5, c.get('label', ''))
            # Titolo
            self.set_font('Helvetica', '', 8)
            x_tit = self.MARGIN + col_label
            self.rect(x_tit, y0, col_tit, row_h, 'DF')
            self.set_xy(x_tit + 2, y0 + (row_h - len(lt) * 5) / 2)
            self.multi_cell(col_tit - 4, 5, vt)
            # Catasto
            x_cat = x_tit + col_tit
            self.rect(x_cat, y0, col_cat, row_h, 'DF')
            self.set_xy(x_cat + 2, y0 + (row_h - len(lc) * 5) / 2)
            self.multi_cell(col_cat - 4, 5, vc)
            # Esito
            x_es = x_cat + col_cat
            self.rect(x_es, y0, col_esito, row_h, 'DF')
            esito = c.get('esito', 'ok')
            if esito == 'ok':
                self.set_text_color(*self.GREEN)
                txt = 'OK'
            elif esito == 'warning':
                self.set_text_color(*self.ORANGE)
                txt = 'ATTENZIONE'
            else:
                self.set_text_color(*self.RED)
                txt = 'DISCORDANZA'
            self.set_font('Helvetica', 'B', 8)
            self.set_xy(x_es + 1, y0 + (row_h - 5) / 2)
            self.cell(col_esito - 2, 5, txt, align='C')
            self.set_y(y0 + row_h)
        self.ln(4)


def generate_report_pdf(data):
    """Genera PDF report pratica.

    data: dict con keys practice_id, date, user, immobile, titolo,
          venditori, acquirenti, verifiche, ipotecaria, riepilogo.
    """
    pdf = ReportPDF(practice_id=data.get('practice_id', ''))
    pdf.alias_nb_pages()
    pdf.add_page()

    # ── Intestazione ──
    parts = []
    if data.get('practice_id'):
        parts.append(f"Pratica: {data['practice_id']}")
    if data.get('date'):
        parts.append(f"Data: {data['date']}")
    if data.get('user'):
        parts.append(f"Utente: {data['user']}")
    if parts:
        pdf.set_font('Helvetica', '', 9)
        pdf.set_text_color(*ReportPDF.MUTED)
        pdf.set_x(ReportPDF.MARGIN)
        pdf.cell(ReportPDF.TABLE_W, 6, '  |  '.join(parts), align='C',
                 new_x='LMARGIN', new_y='NEXT')
        pdf.ln(2)

    # ── Immobile ──
    if data.get('immobile'):
        pdf.section_title('Immobile')
        pdf.kv_table(data['immobile'])

    # ── Dati dal Titolo ──
    if data.get('titolo'):
        pdf.section_title('Analisi Titolo')
        pdf.kv_table(data['titolo'])

    # ── Parti ──
    has_parti = data.get('venditori') or data.get('acquirenti')
    if has_parti:
        pdf.section_title('Parti')
        if data.get('venditori'):
            pdf.sub_title('Venditori (proprietari attuali)')
            rows = []
            for i, v in enumerate(data['venditori']):
                det = []
                if v.get('cf'):
                    det.append(f"CF: {v['cf']}")
                if v.get('diritto'):
                    det.append(v['diritto'])
                if v.get('quota'):
                    det.append(f"quota {v['quota']}")
                val = v.get('nominativo', '?')
                if det:
                    val += ' \u2014 ' + ', '.join(det)
                rows.append((f'#{i+1}', val))
            pdf.kv_table(rows, key_w=20)
        if data.get('acquirenti'):
            pdf.sub_title('Acquirenti')
            rows = []
            for i, a in enumerate(data['acquirenti']):
                val = a.get('nominativo', '?')
                if a.get('cf'):
                    val += f" \u2014 CF: {a['cf']}"
                rows.append((f'#{i+1}', val))
            pdf.kv_table(rows, key_w=20)

    # ── Esito Verifiche ──
    if data.get('verifiche'):
        pdf.section_title('Esito Verifiche')
        pdf.check_table(data['verifiche'])

    # ── Ispezione Ipotecaria ──
    if data.get('ipotecaria'):
        pdf.section_title('Ispezione Ipotecaria')
        for isp in data['ipotecaria']:
            rows = []
            if isp.get('nominativo'):
                rows.append(('Soggetto', isp['nominativo']))
            if isp.get('cf'):
                rows.append(('Codice Fiscale', isp['cf']))
            if isp.get('num_formalita') is not None:
                rows.append(('N. formalit\u00e0', str(isp['num_formalita'])))
            if isp.get('costo'):
                rows.append(('Costo', f"\u20ac {isp['costo']}"))
            pdf.kv_table(rows)
            # Dettaglio formalità
            if isp.get('formalita'):
                pdf.sub_title('Formalit\u00e0')
                frows = []
                for j, f in enumerate(isp['formalita']):
                    desc = f.get('descrizione', '?')
                    dt = f.get('data', '')
                    qual = f.get('qualifica', '')
                    canc = ' [CANCELLATA]' if f.get('cancellata') else ''
                    val = desc
                    if dt:
                        val += f' \u2014 {dt}'
                    if qual:
                        val += f' \u2014 {qual}'
                    if f.get('specie_atto'):
                        val += f' ({f["specie_atto"]})'
                    val += canc
                    frows.append((f'#{j+1}', val))
                pdf.kv_table(frows, key_w=20)

    # ── Riepilogo ──
    if data.get('riepilogo'):
        pdf.section_title('Riepilogo')
        r = data['riepilogo']
        rows = [
            ('Verifiche eseguite', str(r.get('total', 0))),
            ('Esito positivo', str(r.get('ok', 0))),
            ('Discordanze', str(r.get('errors', 0))),
        ]
        if r.get('warnings', 0) > 0:
            rows.append(('Attenzione', str(r['warnings'])))
        esito = 'OK' if r.get('errors', 0) == 0 else 'CON CRITICIT\u00c0'
        rows.append(('Esito complessivo', esito))
        pdf.kv_table(rows)
        # Lista criticità
        if r.get('criticita'):
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(*ReportPDF.RED)
            pdf.set_x(ReportPDF.MARGIN)
            pdf.cell(ReportPDF.TABLE_W, 7, 'Criticit\u00e0:', new_x='LMARGIN', new_y='NEXT')
            pdf.set_font('Helvetica', '', 9)
            for c in r['criticita']:
                pdf.set_x(ReportPDF.MARGIN + 5)
                pdf.cell(ReportPDF.TABLE_W - 5, 6, f'\u2022 {c}', new_x='LMARGIN', new_y='NEXT')
            pdf.ln(4)

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()
