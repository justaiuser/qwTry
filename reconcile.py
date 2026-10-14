"""Local extraction and conservative one-to-one reconciliation."""
import io
import os
import re
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

import fitz
import pandas as pd

COLUMNS = ['Дата', 'Документ', 'Сумма']


def money(value):
    if pd.isna(value) or str(value).strip() == '':
        raise ValueError('Пустая сумма')
    text = str(value).replace('\u00a0', '').replace(' ', '').replace('−', '-').replace(',', '.')
    try:
        result = Decimal(text)
        if not result.is_finite():
            raise InvalidOperation
        return int((result * 100).quantize(Decimal('1')))
    except InvalidOperation as exc:
        raise ValueError(f'Некорректная сумма: {value}') from exc


def extract_pdf(data, progress=None):
    texts = []
    with fitz.open(stream=data, filetype='pdf') as pdf:
        if pdf.needs_pass:
            raise ValueError('PDF защищён паролем. Загрузите копию без пароля.')
        if len(pdf) > 100:
            raise ValueError('Максимум 100 страниц в одном PDF.')
        for i, page in enumerate(pdf):
            text = page.get_text().strip()
            if len(text) < 40:
                with tempfile.TemporaryDirectory() as folder:
                    filename = Path(folder) / 'page.png'
                    page.get_pixmap(dpi=220).save(filename)
                    cmd = ['tesseract', str(filename), 'stdout', '-l', 'rus', '--psm', '6']
                    tessdata = os.environ.get('RECON_TESSDATA', '/workspace/.reconciliation/tessdata')
                    if Path(tessdata, 'rus.traineddata').exists():
                        cmd += ['--tessdata-dir', tessdata]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if result.returncode:
                        raise ValueError('Ошибка OCR: ' + result.stderr[-1000:])
                    text = result.stdout
            texts.append(text)
            if progress:
                progress((i + 1) / len(pdf))
    return '\n\n'.join(texts)


def suggest_rows(text):
    rows = []
    for line in text.splitlines():
        date = re.search(r'\b\d{2}[./]\d{2}[./]\d{4}\b', line)
        amounts = list(re.finditer(r'(?<!\d)-?(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)[,.]\d{2}(?!\d)', line))
        if not date or not amounts:
            continue
        doc = re.search(r'(?:№|N\b)\s*([\w/-]+)', line, re.I)
        rows.append({'Дата': date.group().replace('/', '.'),
                     'Документ': doc.group(1) if doc else '',
                     'Сумма': amounts[-1].group().strip()})
    return pd.DataFrame(rows, columns=COLUMNS)


def normalize(frame):
    result = []
    for n, row in frame.iterrows():
        if all(pd.isna(row.get(c)) or str(row.get(c)).strip() == '' for c in COLUMNS):
            continue
        try:
            date = pd.to_datetime(row['Дата'], dayfirst=True, errors='raise')
            if pd.isna(date):
                raise ValueError('Пустая дата')
            doc = '' if pd.isna(row['Документ']) else str(row['Документ']).strip()
            result.append({'Дата': date.strftime('%d.%m.%Y'), 'Документ': doc,
                           'Сумма': money(row['Сумма']) / 100,
                           '_amount': money(row['Сумма']),
                           '_doc': re.sub(r'\s+', '', doc).casefold().removeprefix('№'),
                           '_day': date.date()})
        except (ValueError, TypeError) as exc:
            raise ValueError(f'Строка {n + 1}: {exc}') from exc
    return result


def compare(ours, theirs, tolerance_days=3, tolerance_cents=0):
    left, right = normalize(ours), normalize(theirs)
    used = set()
    output = []
    def emit(status, a=None, b=None):
        output.append({'Статус': status,
                       'Наш документ': a['Документ'] if a else '',
                       'Документ контрагента': b['Документ'] if b else '',
                       'Наша дата': a['Дата'] if a else '',
                       'Дата контрагента': b['Дата'] if b else '',
                       'Наша сумма': a['Сумма'] if a else None,
                       'Сумма контрагента': b['Сумма'] if b else None,
                       'Разница': round(a['Сумма'] - b['Сумма'], 2) if a and b else None})
    def compatible(a, b):
        return bool(a['_doc']) and a['_doc'] == b['_doc'] and abs((a['_day'] - b['_day']).days) <= tolerance_days
    # Only mutually unique pairs are matched, so duplicate documents are never silently consumed.
    candidates = {i: [j for j,b in enumerate(right) if compatible(a,b) and abs(a['_amount']-b['_amount']) <= tolerance_cents] for i,a in enumerate(left)}
    for i,a in enumerate(left):
        matches = candidates[i]
        if len(matches) == 1 and sum(matches[0] in v for v in candidates.values()) == 1:
            j = matches[0]; used.add(j)
            emit('Совпадает' if a['_day'] == right[j]['_day'] else 'Разница дат', a, right[j])
        elif matches:
            emit('Неоднозначное совпадение', a)
        else:
            same = [j for j,b in enumerate(right) if j not in used and a['_doc'] and a['_doc'] == b['_doc']]
            if len(same) == 1 and not any(same[0] in v for v in candidates.values()) and sum(x['_doc']==a['_doc'] for x in left)==1:
                j = same[0]; used.add(j); emit('Расхождение', a, right[j])
            else:
                emit('Только у нас' if a['_doc'] else 'Нет номера документа', a)
    for j,b in enumerate(right):
        if j not in used:
            emit('Только у контрагента', b=b)
    return pd.DataFrame(output)


def report_bytes(result):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        result.to_excel(writer, index=False, sheet_name='Сверка')
        ws = writer.sheets['Сверка']
        ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions
        for column in ws.columns:
            ws.column_dimensions[column[0].column_letter].width = 25
        # Escape spreadsheet formulas in document identifiers from untrusted inputs.
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith(('=', '+', '-', '@')):
                    cell.data_type = 's'
    return output.getvalue()
