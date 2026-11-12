"""Small worksheet adapter backed by an XLSX file; reopen per operation.

Atomic writes preserve the last good file. SQLite retains results if Excel locks it.
"""
import os
import tempfile
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils.cell import range_boundaries
from gspread.exceptions import WorksheetNotFound

class LocalWorkbook:
    def __init__(self, path):
        self.path=Path(path).expanduser().resolve()
        if self.path.suffix.lower() != '.xlsx':
            raise ValueError('Choose an .xlsx workbook')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if not self.path.exists():
            self.operation(lambda wb: None, write=True)
        else:
            self.operation(lambda wb: None)

    def operation(self, action, write=False):
        before=self.path.stat().st_mtime_ns if self.path.exists() else None
        wb=load_workbook(self.path) if before is not None else Workbook()
        if before is None: wb.active.title='Videos'
        temp=None
        try:
            result=action(wb)
            if write:
                fd,temp=tempfile.mkstemp(prefix='.uploader-',suffix='.xlsx',dir=self.path.parent)
                os.close(fd)
                wb.save(temp)
                current=self.path.stat().st_mtime_ns if self.path.exists() else None
                if current != before:
                    raise RuntimeError('Workbook changed while saving; sync again to preserve your edits')
                os.replace(temp,self.path)
            return result
        finally:
            wb.close()
            if temp and os.path.exists(temp):os.unlink(temp)

    def worksheet_titles(self):
        return self.operation(lambda wb:list(wb.sheetnames))

    def worksheet(self,title):
        if not self.operation(lambda wb:title in wb.sheetnames):raise WorksheetNotFound(title)
        return LocalWorksheet(self,title)

    def add_worksheet(self,title,**kwargs):
        def add(wb):
            if title not in wb.sheetnames:wb.create_sheet(title)
        self.operation(add,write=True)
        return LocalWorksheet(self,title)

class LocalWorksheet:
    def __init__(self,book,title):self.book,self.title=book,title

    def get_all_values(self):
        def read(wb):
            rows=[[str(v) if v is not None else '' for v in row] for row in wb[self.title].iter_rows(values_only=True)]
            while rows and not any(rows[-1]):rows.pop()
            for row in rows:
                while row and row[-1]=='':row.pop()
            return rows
        return self.book.operation(read)

    @staticmethod
    def put(ws,row,col,value):
        cell=ws.cell(row,col)
        cell.value=str(value) if value is not None else ''
        cell.data_type='s'
        cell.alignment=Alignment(vertical='top',wrap_text=True)
        if row==1:
            cell.font=Font(bold=True,color='FFFFFF')
            cell.fill=PatternFill('solid',fgColor='16324F')
            ws.freeze_panes='A2'
            ws.column_dimensions[cell.column_letter].width=28

    def append_row(self,values,**kwargs):
        def write(wb):
            ws=wb[self.title]
            row=1 if ws.max_row==1 and all(c.value is None for c in ws[1]) else ws.max_row+1
            for col,value in enumerate(values,1):self.put(ws,row,col,value)
        self.book.operation(write,write=True)

    def batch_update(self,updates,**kwargs):
        def write(wb):
            ws=wb[self.title]
            for update in updates:
                col,row,_,_=range_boundaries(update['range'])
                for offset,values in enumerate(update['values']):
                    for i,value in enumerate(values):self.put(ws,row+offset,col+i,value)
        self.book.operation(write,write=True)
