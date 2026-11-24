import numpy as np
from fastapi.testclient import TestClient
from app import main


class KeywordModel:
    """Textos com 'hospital' ficam ortogonais aos cursos (nenhum curso parecido); o resto fica igual a eles."""
    def encode(self, texts, **kwargs):
        return np.array([[0., 1.] if 'hospital' in t else [1., 0.] for t in texts], dtype=np.float32)


def make_client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'MANAGEMENT_DB', str(tmp_path / 'management.sqlite3'))
    monkeypatch.setattr(main, 'LOGIN_ATTEMPTS', {})
    main.init_management()
    payload, courses = main.load_courses()
    monkeypatch.setattr(main, 'model', KeywordModel())
    monkeypatch.setattr(main, 'courses', courses)
    monkeypatch.setattr(main, 'institution_metadata', payload)
    monkeypatch.setattr(main, 'course_vectors', {
        f: np.tile(np.array([[1., 0.]], dtype=np.float32), (len(courses), 1)) for f in main.FIELD_WEIGHTS})
    client = TestClient(main.app)
    assert client.post('/api/alunos/cadastro', json={'name': 'Ana', 'email': 'ana@example.org',
                                                     'password': 'SenhaSegura123!', 'consent': True}).status_code == 201
    return client


def test_low_affinity_is_flagged_and_counted_for_management(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    good = client.post('/recommend', json={'interesses': 'programação e tecnologia', 'limite': 5}).json()
    assert good['afinidade']['baixa'] is False and good['afinidade']['melhor_similaridade_texto'] == 1.0
    bad = client.post('/recommend', json={'interesses': 'quero trabalhar em hospital', 'limite': 5}).json()
    assert bad['afinidade'] == {'baixa': True, 'limiar': main.LOW_AFFINITY_THRESHOLD, 'melhor_similaridade_texto': 0.0}
    assert bad['total_retornado'] == 5  # as opções mais próximas continuam sendo mostradas

    monkeypatch.setenv('GESTAO_PASSWORD', 'senha-forte-de-teste')
    dash = client.get('/api/gestao/dashboard', auth=('gestao', 'senha-forte-de-teste')).json()
    assert dash['sem_curso_proximo'] == 1
    assert [c['sem_curso_proximo'] for c in dash['consultas']] == [True, False]  # mais recente primeiro


def test_hybrid_still_reports_low_text_affinity(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    items = main.riasec_questionnaire()['itens']
    client.post('/api/alunos/riasec', json={'respostas': {i['id']: (5 if i['tipo'] == 'S' else 1) for i in items}})
    res = client.post('/recommend', json={'interesses': 'quero trabalhar em hospital', 'limite': 5}).json()
    # A normalização do modo híbrido não esconde que nenhum curso se parece com o texto.
    assert res['modo'] == 'hibrido' and res['afinidade']['baixa'] is True
    only_profile = client.post('/recommend', json={'limite': 5}).json()
    assert only_profile['afinidade']['baixa'] is False and only_profile['afinidade']['melhor_similaridade_texto'] is None


def test_threshold_is_configurable(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    monkeypatch.setattr(main, 'LOW_AFFINITY_THRESHOLD', -1.0)
    assert client.post('/recommend', json={'interesses': 'quero trabalhar em hospital'}).json()['afinidade']['baixa'] is False
