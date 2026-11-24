import json
import numpy as np
from fastapi.testclient import TestClient
from app import main

class FakeModel:
    def encode(self, texts, **kwargs):
        return np.array([[1., 0.] for _ in texts], dtype=np.float32)

def test_endpoints_without_downloading_model(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "MANAGEMENT_DB", str(tmp_path / "management.sqlite3"))
    main.init_management()
    payload, courses = main.load_courses()
    monkeypatch.setattr(main, 'model', FakeModel())
    monkeypatch.setattr(main, 'courses', courses)
    monkeypatch.setattr(main, 'institution_metadata', payload)
    monkeypatch.setattr(main, 'course_vectors', {
        f: np.tile(np.array([[1., 0.]], dtype=np.float32), (len(courses), 1)) for f in main.FIELD_WEIGHTS
    })
    client = TestClient(main.app)
    assert client.get('/health').json()['status'] == 'ok'
    assert client.get('/metadata').json()['total_ofertas'] == len(courses)
    assert client.get('/').status_code == 200
    assert client.post('/recommend', json={'interesses': 'programação e tecnologia', 'limite': 5}).status_code == 401
    registered = client.post('/api/alunos/cadastro', json={'name':'Aluno Teste','email':'aluno@example.com','password':'SenhaTeste123!','consent':True})
    assert registered.status_code == 201, registered.text
    assert client.post('/recommend', json={'interesses': 'programação e tecnologia', 'limite': 5}).json()['total_retornado'] == 5
    assert len(client.get('/api/alunos/historico').json()) == 1
    assert client.get('/api/gestao/dashboard').status_code == 401
    monkeypatch.setenv('GESTAO_PASSWORD','teste-forte')
    dashboard = client.get('/api/gestao/dashboard',auth=('gestao','teste-forte')).json()
    assert dashboard['total_consultas'] == 1 and dashboard['alunos_distintos'] == 1
    assert dashboard['consultas'][0]['aluno'] == 'Aluno Teste'
    assert client.post('/recommend', json={'interesses': 'abc'}).status_code == 422
    assert client.post('/recommend', json={'interesses': '   abc  '}).status_code == 422
    assert client.post('/recommend', json={'interesses': 'x' * 2001}).status_code == 422
    assert client.post('/recommend', json={'interesses': 'programação', 'limite': 47}).status_code == 422
    assert client.delete('/api/alunos/conta').status_code == 200
    assert client.get('/api/alunos/historico').status_code == 401
    assert client.get('/api/gestao/dashboard',auth=('gestao','teste-forte')).json()['total_consultas'] == 0
