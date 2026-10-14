"""Native desktop interface; all inference runs in a background thread locally."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import pandas as pd
from reconcile import COLUMNS, compare, report_bytes, money
from qwen_local import QwenReader

class App:
    def __init__(self, root):
        self.root=root; root.title('Сверка актов · Qwen3-VL'); root.geometry('1250x850')
        self.events=queue.Queue(); self.reader=None; self.reader_key=None; self.busy=False
        self.result=None; self.reviewed=tk.BooleanVar(); self.flip=tk.BooleanVar()
        self.status=tk.StringVar(value='Выберите локальную папку весов Qwen3-VL-4B-Instruct.')
        self.model=tk.StringVar(); self.device=tk.StringVar(value='auto')
        self.pdf=tk.StringVar(); self.excel=tk.StringVar()
        self.side=tk.StringVar(value='Левая'); self.split=tk.IntVar(value=56)
        self.first=tk.IntVar(value=1); self.last=tk.StringVar(value='1')
        self.days=tk.IntVar(value=3); self.cents=tk.IntVar(value=0)
        top=ttk.Frame(root,padding=10); top.pack(fill='x')
        for label,var,kind in [('Папка весов',self.model,'model'),('PDF контрагента',self.pdf,'pdf'),('Наш Excel',self.excel,'excel')]:
            row=ttk.Frame(top); row.pack(fill='x',pady=3)
            ttk.Label(row,text=label,width=20).pack(side='left')
            ttk.Entry(row,textvariable=var,state='readonly').pack(side='left',fill='x',expand=True)
            ttk.Button(row,text='Выбрать',command=lambda v=var,k=kind:self.choose(v,k)).pack(side='left')
        row=ttk.Frame(top); row.pack(fill='x')
        ttk.Label(row,text='Устройство').pack(side='left')
        ttk.Combobox(row,textvariable=self.device,values=['auto','cuda','cpu'],state='readonly',width=8).pack(side='left')
        self.ocr=ttk.Button(row,text='Распознать PDF через Qwen',command=self.recognize); self.ocr.pack(side='left',padx=8)
        ttk.Button(row,text='Загрузить Excel',command=self.load_excel).pack(side='left')
        row=ttk.Frame(top); row.pack(fill='x',pady=5)
        ttk.Label(row,text='Сторона PDF').pack(side='left')
        ttk.Combobox(row,textvariable=self.side,values=['Левая','Правая','Вся страница'],state='readonly',width=14).pack(side='left')
        ttk.Label(row,text='Граница сторон (%)').pack(side='left')
        ttk.Spinbox(row,from_=20,to=80,textvariable=self.split,width=5).pack(side='left')
        ttk.Label(row,text='Страницы с').pack(side='left')
        ttk.Spinbox(row,from_=1,to=100,textvariable=self.first,width=5).pack(side='left')
        ttk.Label(row,text='по (пусто = до конца)').pack(side='left')
        ttk.Entry(row,textvariable=self.last,width=5).pack(side='left')
        ttk.Label(top,text='Все документы и веса остаются на вашем компьютере. Интернет для распознавания не используется.').pack(anchor='w',pady=5)
        self.notebook=ttk.Notebook(root); self.notebook.pack(fill='both',expand=True,padx=10)
        self.tables={}
        for key,label in [('ours','Наши операции'),('theirs','Контрагент')]:
            panel=ttk.Frame(self.notebook); self.notebook.add(panel,text=label)
            tree=ttk.Treeview(panel,columns=COLUMNS,show='headings',selectmode='extended')
            for col in COLUMNS: tree.heading(col,text=col); tree.column(col,width=220)
            tree.pack(fill='both',expand=True); tree.bind('<Double-1>',self.edit)
            bar=ttk.Frame(panel); bar.pack(fill='x')
            ttk.Button(bar,text='Добавить строку',command=lambda t=tree:self.add(t)).pack(side='left')
            ttk.Button(bar,text='Удалить выбранные',command=lambda t=tree:self.delete(t)).pack(side='left')
            ttk.Label(bar,text='Двойной щелчок по ячейке — редактирование').pack(side='left',padx=10)
            self.tables[key]=tree
        text_panel=ttk.Frame(self.notebook); self.notebook.add(text_panel,text='Ответ модели и замечания')
        self.raw=tk.Text(text_panel,wrap='word'); self.raw.pack(fill='both',expand=True)
        bottom=ttk.Frame(root,padding=10); bottom.pack(fill='x')
        ttk.Checkbutton(bottom,text='Поменять знак сумм контрагента',variable=self.flip,command=self.invalidate).pack(anchor='w')
        ttk.Checkbutton(bottom,text='Проверены все операции, даты, номера и знаки; остатки и итоги исключены',variable=self.reviewed).pack(anchor='w')
        row=ttk.Frame(bottom); row.pack(fill='x',pady=5)
        ttk.Label(row,text='Допуск дат (дней)').pack(side='left'); ttk.Spinbox(row,from_=0,to=365,textvariable=self.days,width=6).pack(side='left')
        ttk.Label(row,text='Допуск сумм (коп.)').pack(side='left'); ttk.Spinbox(row,from_=0,to=10000,textvariable=self.cents,width=6).pack(side='left')
        ttk.Button(row,text='Сверить и сохранить отчет Excel',command=self.reconcile).pack(side='left',padx=15)
        ttk.Label(bottom,textvariable=self.status,wraplength=1150).pack(anchor='w')
        root.after(150,self.poll)
    def invalidate(self): self.reviewed.set(False); self.result=None
    def choose(self,var,kind):
        if self.busy: return
        value=filedialog.askdirectory() if kind=='model' else filedialog.askopenfilename(filetypes=[('PDF','*.pdf')] if kind=='pdf' else [('Excel','*.xlsx')])
        if value:
            var.set(value); self.invalidate()
            if kind in ('pdf','excel'):
                self.tables['theirs' if kind=='pdf' else 'ours'].delete(*self.tables['theirs' if kind=='pdf' else 'ours'].get_children())
    def set_rows(self,key,df):
        t=self.tables[key]; t.delete(*t.get_children())
        for row in df[COLUMNS].itertuples(index=False,name=None):
            t.insert('', 'end', values=['' if pd.isna(v) else str(v) for v in row])
        self.invalidate()
    def add(self,t):
        if not self.busy: t.insert('','end',values=['','','']); self.invalidate()
    def delete(self,t):
        if not self.busy: t.delete(*t.selection()); self.invalidate()
    def edit(self,event):
        if self.busy: return
        t=event.widget; row=t.identify_row(event.y); col=t.identify_column(event.x)
        if not row or not col: return
        index=int(col[1:])-1; box=t.bbox(row,col)
        if not box: return
        x,y,w,h=box; entry=ttk.Entry(t)
        entry.place(x=x,y=y,width=w,height=h); entry.insert(0,t.item(row,'values')[index]); entry.focus_set()
        def save(_=None):
            if not entry.winfo_exists(): return
            values=list(t.item(row,'values')); values[index]=entry.get(); t.item(row,values=values); entry.destroy(); self.invalidate()
        entry.bind('<Return>',save); entry.bind('<FocusOut>',save)
    def recognize(self):
        if self.busy: return
        path=self.model.get(); filename=self.pdf.get(); device=self.device.get()
        if not Path(filename).is_file(): messagebox.showerror('PDF','Выберите PDF файл.'); return
        try:
            side=self.side.get(); split=self.split.get(); first=self.first.get()
            last=int(self.last.get()) if self.last.get().strip() else None
            if not 20<=split<=80 or first<1 or (last is not None and last<first):
                raise ValueError('Проверьте границу сторон и диапазон страниц.')
        except (ValueError,tk.TclError) as exc:
            messagebox.showerror('Параметры PDF',str(exc)); return
        self.tables['theirs'].delete(*self.tables['theirs'].get_children())
        self.busy=True; self.invalidate(); self.ocr.state(['disabled']); self.status.set('Загрузка весов…')
        def worker():
            try:
                key=(path,device)
                if self.reader_key != key:
                    self.reader=None
                    self.reader=QwenReader(path,device); self.reader_key=key
                result=self.reader.read_pdf(filename,lambda msg:self.events.put(('status',msg)),side=side,split_percent=split,first_page=first,last_page=last)
                self.events.put(('done',result))
            except Exception as exc: self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='status': self.status.set(value)
                else:
                    self.busy=False; self.ocr.state(['!disabled'])
                    if kind=='error': self.status.set('Распознавание не завершено'); messagebox.showerror('Ошибка',value)
                    else:
                        df,warnings,raw=value; self.set_rows('theirs',df)
                        self.raw.delete('1.0','end'); self.raw.insert('end','\n'.join(warnings)+'\n\n'+raw)
                        self.status.set(f'Распознано {len(df)} операций. Проверьте полноту и замечания модели.')
        except queue.Empty: pass
        self.root.after(150,self.poll)
    def load_excel(self):
        if self.busy: return
        try:
            book=pd.ExcelFile(self.excel.get(),engine='openpyxl')
        except Exception as exc: messagebox.showerror('Excel',str(exc)); return
        dialog=tk.Toplevel(self.root); dialog.title('Колонки Excel'); dialog.geometry('500x440')
        sheet=tk.StringVar(value=book.sheet_names[0]); header=tk.IntVar(value=1)
        sample=pd.read_excel(book,sheet_name=book.sheet_names[0],header=None,nrows=30,dtype=object)
        for idx,row in sample.iterrows():
            values=[str(v).strip().casefold() for v in row if not pd.isna(v)]
            if 'дата' in values and 'документ' in values:
                header.set(idx+1); break
        ttk.Label(dialog,text='Лист').pack(); ttk.Combobox(dialog,textvariable=sheet,values=book.sheet_names,state='readonly').pack()
        ttk.Label(dialog,text='Строка заголовков').pack(); ttk.Spinbox(dialog,from_=1,to=100,textvariable=header).pack()
        area=ttk.Frame(dialog); area.pack(fill='both',expand=True)
        def configure():
            try: df=pd.read_excel(book,sheet_name=sheet.get(),header=header.get()-1,dtype=object)
            except Exception as exc: messagebox.showerror('Excel',str(exc)); return
            for widget in area.winfo_children(): widget.destroy()
            if not len(df.columns): return
            vars=[]; names=[str(c) for c in df.columns]
            defaults=[]
            for term in ['дата','документ','дебет','кредит']:
                defaults.append(next((n for n in names if n.strip().casefold()==term),''))
            for i,label in enumerate(['Дата','Документ','Сумма / дебет','Кредит (если отдельная колонка)']):
                ttk.Label(area,text=label).pack()
                v=tk.StringVar(value=defaults[i] or (names[min(i,len(names)-1)] if i<3 else ''))
                ttk.Combobox(area,textvariable=v,values=names+[''],state='readonly').pack(); vars.append(v)
            filter_dates=tk.BooleanVar(value=True)
            ttk.Checkbutton(area,text='Пропускать строки без даты (сальдо, итоги)',variable=filter_dates).pack()
            def apply():
                try:
                    columns={str(c):c for c in df.columns}
                    date,doc,amount,credit=[v.get() for v in vars]
                    amounts=df[columns[amount]]
                    if credit:
                        def val(v): return 0 if pd.isna(v) or str(v).strip()=='' else money(v)
                        amounts=(amounts.map(val)-df[columns[credit]].map(val))/100
                    operations=pd.DataFrame({'Дата':df[columns[date]],'Документ':df[columns[doc]],'Сумма':amounts})
                    if filter_dates.get():
                        valid=operations['Дата'].map(lambda v: not pd.isna(pd.to_datetime(v,dayfirst=True,errors='coerce')) if not pd.isna(v) else False)
                        removed=int((~valid).sum()); operations=operations.loc[valid].reset_index(drop=True)
                        self.status.set(f'Excel: {len(operations)} операций; исключено {removed} строк без распознаваемой даты. Проверьте полноту.')
                    self.set_rows('ours',operations)
                    dialog.destroy()
                except Exception as exc: messagebox.showerror('Excel',str(exc))
            ttk.Button(area,text='Загрузить выбранные колонки',command=apply).pack(pady=10)
        ttk.Button(dialog,text='Прочитать заголовки',command=configure).pack(); configure()
    def reconcile(self):
        if self.busy: return
        if not self.reviewed.get(): messagebox.showwarning('Проверка','Сначала проверьте обе таблицы и подтвердите проверку.'); return
        try:
            frames={k:pd.DataFrame([t.item(i,'values') for i in t.get_children()],columns=COLUMNS) for k,t in self.tables.items()}
            if any(df.empty for df in frames.values()): raise ValueError('Обе таблицы должны содержать операции.')
            if self.flip.get(): frames['theirs']['Сумма']=frames['theirs']['Сумма'].map(lambda v:-money(v)/100)
            days,cents=self.days.get(),self.cents.get()
            if not 0<=days<=365 or not 0<=cents<=10000: raise ValueError('Допуски вне разрешенного диапазона.')
            result=compare(frames['ours'],frames['theirs'],days,cents)
            path=filedialog.asksaveasfilename(defaultextension='.xlsx',initialfile='сверка.xlsx',filetypes=[('Excel','*.xlsx')])
            if path:
                Path(path).write_bytes(report_bytes(result))
                self.status.set(f'Отчет сохранен: {path}. Совпадает: {(result["Статус"]=="Совпадает").sum()}; требуют проверки: {(result["Статус"]!="Совпадает").sum()}.')
        except Exception as exc: messagebox.showerror('Сверка',str(exc))

if __name__=='__main__':
    root=tk.Tk(); App(root); root.mainloop()
