import hashlib
import io
import pandas as pd
import streamlit as st
from reconcile import COLUMNS, extract_pdf, suggest_rows, compare, report_bytes

st.set_page_config(page_title='Сверка актов', page_icon='📑', layout='wide')
st.title('Сверка актов')
st.caption('Акт контрагента в PDF + ваш Excel → операции и расхождения')
st.info('Распознавание выполняется локально в этой среде. Файлы не отправляются в сервисы OCR. Сканы могут содержать ошибки: проверьте каждую распознанную строку, знаки сумм и полноту операций.')
a,b = st.columns(2)
with a:
    pdf = st.file_uploader('Акт контрагента', type=['pdf'])
with b:
    excel = st.file_uploader('Наши операции', type=['xlsx'])
if not pdf or not excel:
    st.write('Загрузите оба файла. Поддерживается Excel .xlsx; .xls предварительно сохраните в .xlsx.')
    st.stop()
if pdf.size > 30*1024*1024 or excel.size > 30*1024*1024:
    st.error('Максимальный размер каждого файла — 30 МБ.'); st.stop()
key = hashlib.sha256(pdf.getvalue()).hexdigest()
if st.button('Распознать PDF', type='primary'):
    try:
        progress = st.progress(0)
        text = extract_pdf(pdf.getvalue(), progress.progress)
        st.session_state['ocr'] = (key, text, suggest_rows(text))
    except Exception as exc:
        st.error(str(exc))
if 'ocr' not in st.session_state or st.session_state['ocr'][0] != key:
    st.stop()
_, text, suggested = st.session_state['ocr']
with st.expander('Текст распознавания — источник для проверки'):
    st.text_area('Распознанный текст', text, height=300)
    st.download_button('Скачать текст', text, 'ocr.txt')
try:
    book = pd.ExcelFile(io.BytesIO(excel.getvalue()), engine='openpyxl')
    c,d = st.columns(2)
    sheet = c.selectbox('Лист Excel', book.sheet_names)
    header = d.number_input('Номер строки заголовков', min_value=1, max_value=100, value=1)
    raw = pd.read_excel(book, sheet_name=sheet, header=header-1, dtype=object)
    if raw.empty or not len(raw.columns):
        st.error('На выбранном листе нет операций.'); st.stop()
    st.dataframe(raw.head(8), hide_index=True)
    cols = list(raw.columns)
    c,d,e = st.columns(3)
    date_col = c.selectbox('Колонка даты', cols)
    doc_col = d.selectbox('Колонка номера документа', cols, index=min(1,len(cols)-1))
    mode = e.selectbox('Суммы в Excel', ['Одна колонка со знаком','Дебет и кредит'])
    if mode == 'Одна колонка со знаком':
        amount_col = st.selectbox('Колонка суммы', cols, index=min(2,len(cols)-1))
        amounts = raw[amount_col]
    else:
        from reconcile import money
        c,d = st.columns(2)
        debit = c.selectbox('Дебет', cols); credit = d.selectbox('Кредит', cols,index=min(1,len(cols)-1))
        def optional_money(v):
            return 0 if pd.isna(v) or str(v).strip()=='' else money(v)
        amounts = (raw[debit].map(optional_money)-raw[credit].map(optional_money))/100
    ours = pd.DataFrame({'Дата':raw[date_col], 'Документ':raw[doc_col], 'Сумма':amounts})
except Exception as exc:
    st.error(f'Ошибка чтения Excel: {exc}'); st.stop()
st.warning('Автоматический разбор PDF предварительный: используется последняя сумма в строке с датой. Он не определяет дебет/кредит и может пропустить операции. Удалите остатки и итоги, исправьте суммы, добавьте пропущенные строки. Обе таблицы должны использовать одинаковые знаки сумм.')
c,d=st.columns(2)
with c:
    st.subheader('Наши операции')
    ours = st.data_editor(ours, num_rows='dynamic', key='ours_'+hashlib.sha256(excel.getvalue()).hexdigest()+str((sheet,header,date_col,doc_col,mode)), use_container_width=True)
with d:
    st.subheader('Операции контрагента')
    theirs = st.data_editor(suggested, num_rows='dynamic', key='theirs_'+key, use_container_width=True)
flip = st.checkbox('Поменять знак сумм контрагента (зеркальный дебет/кредит)')
c,d = st.columns(2)
days=c.number_input('Допустимая разница дат, дней',0,365,3)
cents=d.number_input('Допуск суммы, копеек',0,10000,0)
confirmed=st.checkbox('Я проверил распознавание, полноту операций и знаки сумм; остатки и итоги исключены')
if st.button('Сверить операции', type='primary', disabled=not confirmed):
    try:
        if flip:
            from reconcile import money
            theirs=theirs.copy(); theirs['Сумма']=theirs['Сумма'].map(lambda v:-money(v)/100)
        if ours.empty or theirs.empty:
            raise ValueError('Обе таблицы должны содержать операции.')
        result=compare(ours,theirs,int(days),int(cents))
        counts=result['Статус'].value_counts()
        c,d,e=st.columns(3)
        c.metric('Совпадает',int(counts.get('Совпадает',0)))
        d.metric('Требуют проверки',int((result['Статус']!='Совпадает').sum()))
        e.metric('Строк отчёта',len(result))
        st.dataframe(result,hide_index=True,use_container_width=True)
        st.download_button('Скачать отчёт Excel',report_bytes(result),'сверка.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as exc:
        st.error(str(exc))
