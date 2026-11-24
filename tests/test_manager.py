from fastapi.testclient import TestClient
from app import main


def test_manager_login_session_and_logout(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'MANAGEMENT_DB', str(tmp_path / 'management.sqlite3'))
    monkeypatch.setattr(main, 'LOGIN_ATTEMPTS', {})
    monkeypatch.setenv('GESTAO_USER', 'gestao')
    monkeypatch.setenv('GESTAO_PASSWORD', 'senha-forte-de-teste')
    main.init_management()
    client = TestClient(main.app)

    # Antigo endereço da gestão agora leva à aba da interface única.
    old = client.get('/gestao', follow_redirects=False)
    assert old.status_code == 307 and old.headers['location'] == '/#/gestao'

    assert client.get('/api/gestao/me').status_code == 401
    assert client.get('/api/gestao/dashboard').status_code == 401
    assert client.post('/api/gestao/login', json={'username': 'gestao', 'password': 'errada'}).status_code == 401

    ok = client.post('/api/gestao/login', json={'username': 'gestao', 'password': 'senha-forte-de-teste'})
    assert ok.status_code == 200 and ok.json() == {'username': 'gestao'}
    assert 'httponly' in ok.headers['set-cookie'].lower()
    assert client.get('/api/gestao/me').json() == {'username': 'gestao'}
    assert client.get('/api/gestao/dashboard').status_code == 200
    assert client.get('/api/gestao/export').status_code == 200

    assert client.post('/api/gestao/logout').status_code == 200
    assert client.get('/api/gestao/me').status_code == 401
    assert client.get('/api/gestao/dashboard').status_code == 401


def test_manager_login_requires_configured_password(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'MANAGEMENT_DB', str(tmp_path / 'management.sqlite3'))
    monkeypatch.setattr(main, 'LOGIN_ATTEMPTS', {})
    monkeypatch.delenv('GESTAO_PASSWORD', raising=False)
    main.init_management()
    client = TestClient(main.app)
    assert client.post('/api/gestao/login', json={'username': 'gestao', 'password': ''}).status_code == 401


def test_manager_login_rate_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'MANAGEMENT_DB', str(tmp_path / 'management.sqlite3'))
    monkeypatch.setattr(main, 'LOGIN_ATTEMPTS', {})
    monkeypatch.setenv('GESTAO_PASSWORD', 'senha-forte-de-teste')
    main.init_management()
    client = TestClient(main.app)
    for _ in range(8):
        assert client.post('/api/gestao/login', json={'username': 'gestao', 'password': 'x'}).status_code == 401
    assert client.post('/api/gestao/login', json={'username': 'gestao', 'password': 'senha-forte-de-teste'}).status_code == 429


def test_static_logo_served(monkeypatch, tmp_path):
    client = TestClient(main.app)
    res = client.get('/static/logo-ifs.png')
    assert res.status_code == 200 and res.headers['content-type'] == 'image/png'
