import json
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class IntegrationStructureTests(unittest.TestCase):
    def test_course_ids_match(self):
        data = json.loads((ROOT / 'recomendador_cursos_ifs/data/cursos_ifs.json').read_text())
        with sqlite3.connect(ROOT / 'guia_carreira_ifs/database/banco_recomendacao_ifs.sqlite') as db:
            ids_db = {row[0] for row in db.execute('SELECT id_oferta FROM curso_oferta')}
        ids_ia = {course['id_oferta'] for course in data['ofertas']}
        self.assertEqual(len(ids_ia), 46)
        self.assertEqual(ids_ia, ids_db)

    def test_bridge_routes_exist(self):
        urls = (ROOT / 'guia_carreira_ifs/backend/urls.py').read_text()
        self.assertIn('api/ia/recomendar/', urls)
        self.assertIn('api/ia/metadata/', urls)

    def test_ui_calls_real_backend(self):
        html = (ROOT / 'guia_carreira_ifs/site/index.html').read_text()
        self.assertIn("fetch('/api/ia/recomendar/'", html)
        self.assertNotIn('const DB={"courses"', html)
        self.assertIn('não porcentagem de compatibilidade', html)

if __name__ == '__main__': unittest.main()
