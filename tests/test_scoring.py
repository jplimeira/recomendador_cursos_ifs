import numpy as np
import pytest
from app.scoring import DEFAULT_WEIGHTS, rank_courses, validate_weights


def test_weights_are_valid():
    assert sum(validate_weights(DEFAULT_WEIGHTS).values()) == pytest.approx(1)
    with pytest.raises(ValueError):
        validate_weights({**DEFAULT_WEIGHTS, 'descricao': .99})
    with pytest.raises(ValueError):
        validate_weights({**DEFAULT_WEIGHTS, 'descricao': -0.01})


def test_ranking_filters_and_explanations():
    courses = [
        {'id_oferta': 'a', 'nome': 'A', 'campus': 'X', 'nivel': 'Graduação'},
        {'id_oferta': 'b', 'nome': 'B', 'campus': 'Y', 'nivel': 'Técnico'},
    ]
    vectors = {field: np.array([[1., 0.], [0., 1.]], dtype=np.float32) for field in DEFAULT_WEIGHTS}
    results = rank_courses(np.array([1., 0.]), courses, vectors, DEFAULT_WEIGHTS)
    assert [r['id_oferta'] for r in results] == ['a', 'b']
    assert results[0]['score'] == pytest.approx(1)
    assert len(results[0]['detalhamento']) == 6
    assert [r['id_oferta'] for r in rank_courses(np.array([1., 0.]), courses, vectors, DEFAULT_WEIGHTS, campus='Y')] == ['b']
    assert rank_courses(np.array([1., 0.]), courses, vectors, DEFAULT_WEIGHTS, campus='Z') == []
    assert len(rank_courses(np.array([1., 0.]), courses, vectors, DEFAULT_WEIGHTS, limite=1)) == 1


def test_stable_tie_break():
    courses = [{'id_oferta': str(i), 'campus': 'X', 'nivel': 'T'} for i in range(3)]
    vectors = {field: np.ones((3, 2), dtype=np.float32) for field in DEFAULT_WEIGHTS}
    assert [x['id_oferta'] for x in rank_courses(np.ones(2), courses, vectors, DEFAULT_WEIGHTS)] == ['0', '1', '2']
