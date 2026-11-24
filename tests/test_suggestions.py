from fastapi.testclient import TestClient
from app import main


def make_client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'MANAGEMENT_DB', str(tmp_path / 'management.sqlite3'))
    monkeypatch.setattr(main, 'LOGIN_ATTEMPTS', {})
    payload, courses = main.load_courses()
    monkeypatch.setattr(main, 'courses', courses)
    monkeypatch.setenv('GESTAO_PASSWORD', 'senha-forte-de-teste')
    main.init_management()
    return TestClient(main.app)


def register(client, email, name='Estudante'):
    r = client.post('/api/alunos/cadastro', json={'name': name, 'email': email, 'password': 'SenhaSegura123!', 'consent': True})
    assert r.status_code == 201, r.text


def test_student_suggestion_flow_and_management_view(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    url = '/api/alunos/sugestoes'
    assert client.post(url, json={'course_name': 'Enfermagem', 'reason': 'Faltam técnicos.'}).status_code == 401

    register(client, 'a@example.org', 'Ana')
    assert client.post(url, json={'course_name': 'En', 'reason': 'Motivo suficiente.'}).status_code == 422
    assert client.post(url, json={'course_name': 'Enfermagem', 'reason': 'curto'}).status_code == 422
    first = client.post(url, json={'course_name': 'Enfermagem', 'reason': 'Faltam técnicos na região.',
                                   'campus': 'Lagarto', 'nivel': 'Técnico Subsequente', 'area': 'Saúde'})
    assert first.status_code == 201, first.text
    assert first.json()['campus'] == 'Lagarto'
    # Campus e nível fora da lista são descartados em vez de gravados.
    odd = client.post(url, json={'course_name': 'Informática', 'reason': 'Quero estudar perto de casa.',
                                 'campus': 'Campus Inventado', 'nivel': 'Doutorado'}).json()
    assert odd['campus'] is None and odd['nivel'] is None
    assert len(client.get(url).json()) == 2

    # Outro estudante sugere o mesmo curso com outra grafia.
    client.cookies.clear()
    register(client, 'b@example.org', 'Bruno')
    assert client.post(url, json={'course_name': '  enfermagem ', 'reason': 'Muita procura por saúde aqui.'}).status_code == 201
    assert len(client.get(url).json()) == 1  # cada um vê só as próprias

    client.cookies.clear()
    assert client.get('/api/gestao/sugestoes').status_code == 401
    assert client.post('/api/gestao/login', json={'username': 'gestao', 'password': 'senha-forte-de-teste'}).status_code == 200
    data = client.get('/api/gestao/sugestoes').json()
    assert data['total_sugestoes'] == 3 and data['estudantes'] == 2 and data['cursos_distintos'] == 2
    top = data['ranking'][0]
    assert top['curso'] in ('Enfermagem', 'enfermagem') and top['estudantes'] == 2 and top['ja_ofertado_em'] == []
    informatica = next(r for r in data['ranking'] if r['curso'] == 'Informática')
    assert informatica['ja_ofertado_em']  # já existe no catálogo
    assert client.get('/api/gestao/sugestoes', params={'campus': 'Lagarto'}).json()['total_sugestoes'] == 1
    assert client.get('/api/gestao/sugestoes', params={'search': 'saúde'}).json()['total_sugestoes'] == 2  # área de uma, motivo da outra
    assert client.get('/api/gestao/sugestoes', params={'search': 'técnicos'}).json()['total_sugestoes'] == 1
    assert client.get('/api/gestao/sugestoes', params={'period': 3}).status_code == 422
    csv = client.get('/api/gestao/sugestoes/export')
    assert csv.status_code == 200 and 'Enfermagem' in csv.text


def test_student_can_delete_only_own_suggestion_and_account_cleanup(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    register(client, 'a@example.org')
    own = client.post('/api/alunos/sugestoes', json={'course_name': 'Design de Games', 'reason': 'Mercado em crescimento.'}).json()
    client.cookies.clear()
    register(client, 'b@example.org')
    assert client.delete(f"/api/alunos/sugestoes/{own['id']}").status_code == 404
    client.post('/api/alunos/sugestoes', json={'course_name': 'Energia Solar', 'reason': 'Muito sol em Sergipe.'})
    assert client.delete('/api/alunos/conta').status_code == 200
    with main.management_connection() as db:
        assert db.execute('SELECT COUNT(*) FROM course_suggestions').fetchone()[0] == 1


def test_daily_suggestion_limit_and_csv_formula_escape(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    register(client, 'a@example.org')
    for i in range(main.SUGGESTIONS_PER_DAY):
        assert client.post('/api/alunos/sugestoes', json={'course_name': f'=Curso {i}', 'reason': 'Motivo de teste.'}).status_code == 201
    assert client.post('/api/alunos/sugestoes', json={'course_name': 'Mais um', 'reason': 'Motivo de teste.'}).status_code == 429
    client.cookies.clear()
    client.post('/api/gestao/login', json={'username': 'gestao', 'password': 'senha-forte-de-teste'})
    text = client.get('/api/gestao/sugestoes/export').text
    assert ";'=Curso 0;" in text and ';=Curso' not in text
