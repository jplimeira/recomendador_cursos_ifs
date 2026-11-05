import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
class SimplifiedFormTests(unittest.TestCase):
    def test_student_ui_has_two_inputs_only(self):
        html = (ROOT/'guia_carreira_ifs/site/index.html').read_text(encoding='utf-8')
        self.assertIn('id="name"', html)
        self.assertIn('id="description"', html)
        for removed in ('id="age"', 'id="city"', 'id="interests"', 'id="skills"', 'id="goals"', 'id="level"', 'id="campus"', 'id="transporte"', 'id="transportForm"', 'href="#transporte"'):
            self.assertNotIn(removed, html)
        self.assertIn("description:$('description').value.trim()", html)
    def test_backend_accepts_description(self):
        backend = (ROOT/'guia_carreira_ifs/backend/core/views.py').read_text(encoding='utf-8')
        self.assertIn("data.get('description')", backend)
        self.assertIn("'interesses': text", backend)
if __name__=='__main__': unittest.main()
