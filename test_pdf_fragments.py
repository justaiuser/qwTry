import json
import tempfile
import unittest
from pathlib import Path
import fitz
from pdf_fragments import fragment_page,merge_boundary
from qwen_local import QwenReader
from reconcile import document_number

class FragmentTests(unittest.TestCase):
    def test_boundaries_and_sides(self):
        with fitz.open() as pdf:
            page=pdf.new_page(width=600,height=840)
            for y in range(150,800,30): page.draw_line((20,y),(570,y),width=1)
            for side in ['Левая','Правая','Вся страница']:
                parts=fragment_page(page,side)
                self.assertGreater(len(parts),1)
                self.assertTrue(all(im.width<=1100 and im.height<=720 for im,_ in parts))
            with self.assertRaises(ValueError): fragment_page(page,'Левая',99)
    def test_overlap_preserves_other_duplicates(self):
        a={'Документ':'1'}; b={'Документ':'2'}
        rows,n=merge_boundary([a,a,b],[b,a],True)
        self.assertEqual(rows,[a,a,b,a]); self.assertEqual(n,1)
        rows,n=merge_boundary([a],[a],False)
        self.assertEqual(rows,[a,a]); self.assertEqual(n,0)
    def test_range_and_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            filename=Path(folder)/'sample.pdf'
            with fitz.open() as pdf:
                pdf.new_page(); pdf.new_page(); pdf.save(filename)
            reader=QwenReader.__new__(QwenReader)
            reader.read_page=lambda image: json.dumps({'operations':[],'warnings':[]})
            progress=[]
            rows,warnings,raw=reader.read_pdf(filename,progress.append,first_page=1,last_page=1)
            self.assertTrue(rows.empty)
            self.assertTrue(progress)
            self.assertNotIn('Страница 2',raw)
            self.assertTrue(any('не извлекла' in w for w in warnings))
            with self.assertRaises(ValueError): reader.read_pdf(filename,first_page=3)
    def test_document_description(self):
        self.assertEqual(document_number('Продажа (00501006 от 05.01.2026)'), '00501006')
        self.assertEqual(document_number('00123'),'00123')

if __name__=='__main__': unittest.main()
