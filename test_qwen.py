import unittest
from qwen_local import parse_response, QwenReader

class QwenOutputTests(unittest.TestCase):
    def test_debit_credit_and_leading_zero(self):
        rows,warnings=parse_response('```json\n{"operations":[{"date":"01.01.2026","document":"0012","debit":"1234.56","credit":"34.56"}],"warnings":[]}\n```')
        self.assertEqual(rows[0]['Документ'],'0012')
        self.assertEqual(rows[0]['Сумма'],'1200.00')
        self.assertEqual(warnings,[])
    def test_missing_values_are_not_invented(self):
        rows,warnings=parse_response('{"operations":[{"date":null,"document":null,"debit":null,"credit":"0.00"}]}')
        self.assertEqual(rows[0]['Сумма'],'')
        self.assertTrue(warnings)
    def test_invalid_or_truncated_output_rejected(self):
        for text in ['not json','{"operations":{}}','```json\n{"operations":[]}', '{"operations":[{"document":12}]}']:
            with self.subTest(text=text),self.assertRaises(ValueError): parse_response(text)
    def test_missing_weights_does_not_download(self):
        with self.assertRaises(ValueError): QwenReader('/nonexistent/local/model')

if __name__=='__main__': unittest.main()
