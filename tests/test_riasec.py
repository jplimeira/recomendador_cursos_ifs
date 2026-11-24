import json
import numpy as np
from fastapi.testclient import TestClient

from app import main
from app.scoring import (RIASEC_TYPES, congruence, holland_code, parse_holland_text,
                         profile_from_answers, profile_is_flat, rank_courses)


# ---------- Regras puras ----------

def test_parse_holland_text_orders_letters_and_component():
    v = parse_holland_text('Investigativo e Realista, com componente Convencional')
    assert v == {'R': 0.7, 'I': 1.0, 'A': 0.0, 'S': 0.0, 'E': 0.0, 'C': 0.4}
    assert holland_code(v) == 'IRC'
    v3 = parse_holland_text('Artístico, Realista e Social')
    assert (v3['A'], v3['R'], v3['S']) == (1.0, 0.7, 0.5)


def test_all_catalog_courses_get_a_profile():
    _, courses = main.load_courses()
    for c in courses:
        assert holland_code(parse_holland_text(c['dimensoes_vocacionais'])), c['nome']


def test_profile_from_answers_requires_every_item():
    items = [{'id': f'{t}{i}', 'tipo': t} for t in RIASEC_TYPES for i in range(2)]
    answers = {it['id']: 3 for it in items}
    answers.update({'I0': 5, 'I1': 5, 'R0': 1, 'R1': 1})
    profile = profile_from_answers(items, answers)
    assert profile['I'] == 1.0 and profile['R'] == 0.0 and profile['A'] == 0.5
    for bad in ({**answers, 'C1': 6}, {k: v for k, v in answers.items() if k != 'S0'}, {**answers, 'E0': True}):
        try:
            profile_from_answers(items, bad)
            raise AssertionError('deveria rejeitar')
        except ValueError:
            pass


def test_congruence_uses_shape_not_level():
    course = {'R': 1.0, 'I': 0.7, 'A': 0, 'S': 0, 'E': 0, 'C': 0}
    high = {'R': .9, 'I': .8, 'A': .5, 'S': .5, 'E': .5, 'C': .5}
    low = {'R': .5, 'I': .4, 'A': .1, 'S': .1, 'E': .1, 'C': .1}  # mesmo formato, nível menor
    opposite = {'R': .1, 'I': .1, 'A': .9, 'S': .9, 'E': .5, 'C': .5}
    assert abs(congruence(high, course) - congruence(low, course)) < 1e-9
    assert congruence(high, course) > 0.9 > 0.5 > congruence(opposite, course)
    flat = {t: .6 for t in RIASEC_TYPES}
    assert congruence(flat, course) is None and profile_is_flat(flat)


def _toy_catalog():
    courses = [
        {'id_oferta': 'A', 'id_perfil': 'P1', 'nome': 'Informática', 'campus': 'X', 'nivel': 'N'},
        {'id_oferta': 'B', 'id_perfil': 'P2', 'nome': 'Turismo', 'campus': 'X', 'nivel': 'N'},
        {'id_oferta': 'C', 'id_perfil': 'P3', 'nome': 'Artes', 'campus': 'X', 'nivel': 'N'},
    ]
    riasec = {'P1': {'R': .7, 'I': 1, 'A': 0, 'S': 0, 'E': 0, 'C': .4},
              'P2': {'R': 0, 'I': 0, 'A': 0, 'S': 1, 'E': .7, 'C': 0},
              'P3': {'R': 0, 'I': 0, 'A': 1, 'S': .5, 'E': 0, 'C': 0}}
    weights = {'descricao': 1.0}
    # O texto favorece "Artes"; o perfil RIASEC favorece "Turismo".
    vectors = {'descricao': np.array([[0.2, 0.0], [0.5, 0.0], [0.9, 0.0]], dtype=np.float32)}
    user = {'R': .1, 'I': .2, 'A': .3, 'S': 1, 'E': .8, 'C': .2}
    return courses, riasec, weights, vectors, user


def test_rank_modes_text_riasec_and_hybrid():
    courses, riasec, weights, vectors, user = _toy_catalog()
    q = np.array([1.0, 0.0], dtype=np.float32)
    text = rank_courses(q, courses, vectors, weights)
    assert [r['nome'] for r in text] == ['Artes', 'Turismo', 'Informática'] and text[0]['metodo'] == 'texto'
    only = rank_courses(None, courses, vectors, weights, riasec_user=user, riasec_courses=riasec)
    assert only[0]['nome'] == 'Turismo' and only[0]['metodo'] == 'riasec' and 'detalhamento' not in only[0]
    hybrid = rank_courses(q, courses, vectors, weights, riasec_user=user, riasec_courses=riasec, riasec_weight=0.5)
    assert hybrid[0]['metodo'] == 'hibrido' and hybrid[-1]['nome'] == 'Informática'
    assert {'score_texto', 'score_riasec', 'codigo_curso'} <= set(hybrid[0])
    # Peso 0 reproduz a ordem do texto; peso 1 reproduz a ordem do perfil.
    assert [r['nome'] for r in rank_courses(q, courses, vectors, weights, riasec_user=user, riasec_courses=riasec, riasec_weight=0)] == [r['nome'] for r in text]
    assert [r['nome'] for r in rank_courses(q, courses, vectors, weights, riasec_user=user, riasec_courses=riasec, riasec_weight=1)] == [r['nome'] for r in only]


def test_flat_profile_falls_back_to_text():
    courses, riasec, weights, vectors, _ = _toy_catalog()
    flat = {t: .5 for t in RIASEC_TYPES}
    res = rank_courses(np.array([1.0, 0.0]), courses, vectors, weights, riasec_user=flat, riasec_courses=riasec)
    assert res[0]['metodo'] == 'texto'


# ---------- API ----------

class FakeModel:
    def encode(self, texts, **kwargs):
        return np.array([[1., 0.] for _ in texts], dtype=np.float32)


def make_client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'MANAGEMENT_DB', str(tmp_path / 'management.sqlite3'))
    monkeypatch.setattr(main, 'LOGIN_ATTEMPTS', {})
    main.init_management()
    payload, courses = main.load_courses()
    monkeypatch.setattr(main, 'model', FakeModel())
    monkeypatch.setattr(main, 'courses', courses)
    monkeypatch.setattr(main, 'institution_metadata', payload)
    monkeypatch.setattr(main, 'course_vectors', {
        f: np.tile(np.array([[1., 0.]], dtype=np.float32), (len(courses), 1)) for f in main.FIELD_WEIGHTS})
    client = TestClient(main.app)
    r = client.post('/api/alunos/cadastro', json={'name': 'Ana', 'email': 'ana@example.org', 'password': 'SenhaSegura123!', 'consent': True})
    assert r.status_code == 201
    return client


def answers_favoring(kind):
    items = main.riasec_questionnaire()['itens']
    return {i['id']: (5 if i['tipo'] == kind else 1) for i in items}


def test_questionnaire_is_public_and_well_formed(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    client.cookies.clear()
    data = client.get('/api/riasec/questionario').json()
    assert len(data['itens']) == 30
    assert sorted({i['tipo'] for i in data['itens']}) == sorted(RIASEC_TYPES)
    assert all(sum(1 for i in data['itens'] if i['tipo'] == t) == 5 for t in RIASEC_TYPES)
    assert [e['valor'] for e in data['escala']] == [1, 2, 3, 4, 5]


def test_profile_save_and_hybrid_recommendation(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    assert client.get('/api/alunos/riasec').status_code == 404
    assert client.post('/recommend', json={'limite': 5}).status_code == 422  # sem texto e sem perfil
    assert client.post('/api/alunos/riasec', json={'respostas': {'R1': 5}}).status_code == 422

    saved = client.post('/api/alunos/riasec', json={'respostas': answers_favoring('S')})
    assert saved.status_code == 200, saved.text
    assert saved.json()['codigo'][0] == 'S' and saved.json()['diferenciado'] is True
    assert client.get('/api/alunos/riasec').json()['codigo'] == saved.json()['codigo']

    only_profile = client.post('/recommend', json={'limite': 5}).json()
    assert only_profile['modo'] == 'riasec' and only_profile['perfil_riasec']['codigo'][0] == 'S'
    assert 'S' in only_profile['resultados'][0]['codigo_curso']

    hybrid = client.post('/recommend', json={'interesses': 'Gosto de turismo e de pessoas', 'limite': 5}).json()
    assert hybrid['modo'] == 'hibrido' and hybrid['peso_riasec'] == main.RIASEC_WEIGHT
    text_only = client.post('/recommend', json={'interesses': 'Gosto de turismo e de pessoas', 'usar_riasec': False, 'limite': 5}).json()
    assert text_only['modo'] == 'texto' and text_only['perfil_riasec'] is None
    assert client.post('/recommend', json={'interesses': 'abc'}).status_code == 422

    monkeypatch.setenv('GESTAO_PASSWORD', 'senha-forte-de-teste')
    dash = client.get('/api/gestao/dashboard', auth=('gestao', 'senha-forte-de-teste')).json()
    assert dash['riasec']['perfis'] == 1
    assert next(x for x in dash['riasec']['predominante'] if x['tipo'] == 'S')['count'] == 1
    assert {c['metodo'] for c in dash['consultas']} == {'riasec', 'hibrido', 'texto'}

    assert client.delete('/api/alunos/riasec').status_code == 200
    assert client.get('/api/alunos/riasec').status_code == 404


def test_flat_answers_do_not_drive_recommendations(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    items = main.riasec_questionnaire()['itens']
    saved = client.post('/api/alunos/riasec', json={'respostas': {i['id']: 3 for i in items}}).json()
    assert saved['diferenciado'] is False
    assert client.post('/recommend', json={'limite': 5}).status_code == 422
    assert client.post('/recommend', json={'interesses': 'programação e tecnologia', 'limite': 5}).json()['modo'] == 'texto'


def test_account_deletion_removes_profile(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    client.post('/api/alunos/riasec', json={'respostas': answers_favoring('R')})
    assert client.delete('/api/alunos/conta').status_code == 200
    with main.management_connection() as db:
        assert db.execute('SELECT COUNT(*) FROM riasec_profiles').fetchone()[0] == 0


def test_course_profile_file_matches_catalog():
    data = json.load(open(main.RIASEC_COURSES_FILE, encoding='utf-8'))['perfis']
    _, courses = main.load_courses()
    assert {c['id_perfil'] for c in courses} == set(data)
    for p in data.values():
        assert set(p['vetor']) == set(RIASEC_TYPES) and all(0 <= v <= 1 for v in p['vetor'].values())


def test_evaluate_compares_modes(monkeypatch, tmp_path):
    make_client(monkeypatch, tmp_path)
    import importlib, sys, types
    monkeypatch.setitem(sys.modules, 'sentence_transformers', types.SimpleNamespace(SentenceTransformer=None))
    ev = importlib.import_module('scripts.evaluate')
    _, courses = main.load_courses()
    social = next(c for c in courses if c['nome'] == 'Turismo')
    cases = [{'interesses': 'gosto de pessoas e viagens', 'relevantes': [social['id_oferta']],
              'riasec': {'R': .1, 'I': .1, 'A': .3, 'S': 1, 'E': .8, 'C': .2}},
             {'interesses': 'tecnologia', 'relevantes': [courses[0]['id_oferta']]}]
    texto = ev.evaluate(cases, mode='texto')
    riasec = ev.evaluate(cases, mode='riasec')
    hibrido = ev.evaluate(cases, mode='hibrido', riasec_weight=0.5)
    assert texto['consultas'] == 2 and riasec['consultas'] == 1 and hibrido['consultas'] == 1
    assert riasec['recall@5'] == 1.0  # perfil Social-Empreendedor encontra Turismo no top 5
