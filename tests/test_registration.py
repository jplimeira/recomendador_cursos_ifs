from fastapi.testclient import TestClient
from app import main


def test_registration_validation_and_login(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'MANAGEMENT_DB', str(tmp_path / 'students.sqlite3'))
    main.init_management()
    client = TestClient(main.app)
    endpoint = '/api/alunos/cadastro'
    valid = {'name': 'Maria Silva', 'email': 'maria@example.org', 'password': 'SenhaSegura123!', 'consent': True}
    assert client.post(endpoint, json={**valid, 'consent': False}).status_code == 422
    assert client.post(endpoint, json={**valid, 'password': 'curta'}).status_code == 422
    assert client.post(endpoint, json={**valid, 'email': 'invalido'}).status_code == 422
    created = client.post(endpoint, json=valid)
    assert created.status_code == 201, created.text
    assert client.get('/api/alunos/me').json()['email'] == valid['email']
    assert client.post(endpoint, json=valid).status_code == 409
    assert client.post('/api/alunos/logout').status_code == 200
    assert client.get('/api/alunos/me').status_code == 401
    assert client.post('/api/alunos/login', json={'email': valid['email'], 'password': 'errada'}).status_code == 401
    assert client.post('/api/alunos/login', json={'email': valid['email'], 'password': valid['password']}).status_code == 200
    assert client.get('/api/alunos/me').status_code == 200
