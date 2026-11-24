"""Regras puras de classificação, separadas da API e do modelo de IA."""
import json
import os
import numpy as np

DEFAULT_WEIGHTS = {
    'interesses_relacionados': .35,
    'habilidades_relacionadas': .20,
    'objetivos_profissionais': .20,
    'areas_atuacao': .15,
    'descricao': .07,
    'dimensoes_vocacionais': .03,
}
FIELD_LABELS = {
    'interesses_relacionados': 'Interesses relacionados',
    'habilidades_relacionadas': 'Habilidades relacionadas',
    'objetivos_profissionais': 'Objetivos profissionais',
    'areas_atuacao': 'Áreas de atuação',
    'descricao': 'Descrição do curso',
    'dimensoes_vocacionais': 'Dimensões vocacionais',
}

def validate_weights(weights):
    if set(weights) != set(DEFAULT_WEIGHTS):
        raise ValueError('Pesos devem conter exatamente as seis dimensões esperadas.')
    try:
        values = [float(weights[k]) for k in DEFAULT_WEIGHTS]
    except (ValueError, TypeError) as exc:
        raise ValueError('Pesos devem ser numéricos.') from exc
    if not all(np.isfinite(v) and v >= 0 for v in values):
        raise ValueError('Pesos devem ser finitos e não negativos.')
    if not np.isclose(sum(values), 1.0, atol=1e-6):
        raise ValueError('A soma dos pesos deve ser 1.0.')
    return dict(zip(DEFAULT_WEIGHTS, values))

def load_weights(path=None):
    if not path:
        return validate_weights(DEFAULT_WEIGHTS)
    with open(path, encoding='utf-8') as handle:
        return validate_weights(json.load(handle))

def rank_courses(query_vector, courses, vectors, weights, campus=None, nivel=None, limite=10):
    """Calcula scores vetorizados e retorna resultados no contrato da API original."""
    if not courses:
        return []
    query = np.asarray(query_vector, dtype=np.float32)
    if query.ndim != 1 or not np.all(np.isfinite(query)):
        raise ValueError('Embedding da consulta inválido.')
    selected = [i for i, c in enumerate(courses)
                if (not campus or campus == 'Todos' or c.get('campus') == campus)
                and (not nivel or nivel == 'Todos' or c.get('nivel') == nivel)]
    if not selected:
        return []
    similarities = {}
    for field in weights:
        matrix = np.asarray(vectors[field], dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(courses) or matrix.shape[1] != query.size:
            raise ValueError(f'Embeddings inconsistentes para {field}.')
        similarities[field] = matrix[selected] @ query
    totals = sum(weights[field] * similarities[field] for field in weights)
    # Ordenação estável preserva a ordem original em empates.
    order = np.argsort(-totals, kind='stable')[:limite]
    results = []
    for position in order:
        course = courses[selected[int(position)]]
        breakdown = {
            field: {
                'label': FIELD_LABELS[field],
                'similaridade': round(float(similarities[field][position]), 4),
                'peso': weight,
                'contribuicao': round(float(similarities[field][position]) * weight, 4),
            } for field, weight in weights.items()
        }
        strongest = max(breakdown, key=lambda f: breakdown[f]['similaridade'])
        results.append({
            **{field: course.get(field) for field in (
                'id_oferta', 'id_perfil', 'nome', 'campus', 'nivel', 'duracao',
                'area_principal', 'descricao', 'interesses_relacionados',
                'habilidades_relacionadas', 'objetivos_profissionais',
                'areas_atuacao', 'dimensoes_vocacionais')},
            'score': round(float(totals[position]), 4),
            'dimensao_mais_proxima': FIELD_LABELS[strongest],
            'detalhamento': breakdown,
        })
    return results
