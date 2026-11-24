"""Regras puras de classificação, separadas da API e do modelo de IA."""
import json
import os
import re
import unicodedata
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

# ---------- Modelo RIASEC de Holland ----------
# Ordem do hexágono de Holland: tipos vizinhos são mais parecidos entre si.
RIASEC_TYPES = ('R', 'I', 'A', 'S', 'E', 'C')
RIASEC_NAMES = {'R': 'Realista', 'I': 'Investigativo', 'A': 'Artístico',
                'S': 'Social', 'E': 'Empreendedor', 'C': 'Convencional'}
_NAME_TO_TYPE = {'realista': 'R', 'investigativo': 'I', 'artistico': 'A',
                 'social': 'S', 'empreendedor': 'E', 'convencional': 'C'}
MAIN_POSITION_WEIGHTS = (1.0, 0.7, 0.5)
COMPONENT_WEIGHT = 0.4


def _plain(text):
    return unicodedata.normalize('NFD', str(text or '')).encode('ascii', 'ignore').decode().casefold()


def parse_holland_text(text):
    """Converte "Realista e Convencional, com componente Investigativo" em vetor 0..1 por tipo."""
    vector = {t: 0.0 for t in RIASEC_TYPES}
    plain = _plain(text)
    main_part, _, component_part = plain.partition('com componente')
    main_types = [_NAME_TO_TYPE[w] for w in re.findall(r'[a-z]+', main_part) if w in _NAME_TO_TYPE]
    for position, t in enumerate(main_types[:len(MAIN_POSITION_WEIGHTS)]):
        vector[t] = max(vector[t], MAIN_POSITION_WEIGHTS[position])
    for w in re.findall(r'[a-z]+', component_part):
        if w in _NAME_TO_TYPE:
            t = _NAME_TO_TYPE[w]
            vector[t] = max(vector[t], COMPONENT_WEIGHT)
    return vector


def holland_code(vector, size=3):
    """Letras com maior pontuação, em ordem (ex.: 'IRC'). Ignora tipos zerados."""
    ranked = sorted((t for t in RIASEC_TYPES if vector.get(t, 0) > 0),
                    key=lambda t: (-vector[t], RIASEC_TYPES.index(t)))
    return ''.join(ranked[:size])


def profile_from_answers(items, answers, scale_min=1, scale_max=5):
    """Média das respostas de cada tipo, reescalada para 0..1. Exige todas as respostas."""
    by_type = {t: [] for t in RIASEC_TYPES}
    for item in items:
        value = answers.get(item['id'])
        if not isinstance(value, int) or isinstance(value, bool) or not scale_min <= value <= scale_max:
            raise ValueError(f"Resposta ausente ou inválida para o item {item['id']}.")
        by_type[item['tipo']].append(value)
    span = scale_max - scale_min
    return {t: round((sum(v) / len(v) - scale_min) / span, 4) for t, v in by_type.items() if v}


def congruence(user, course):
    """Correlação de Pearson entre os perfis, reescalada para 0..1.

    Centralizar cada perfil na própria média evita o defeito do cosseno puro: quem responde
    tudo alto e quem responde tudo baixo não são tratados como iguais ao curso. Retorna None
    quando o perfil do estudante não tem diferenciação (todas as letras iguais).
    """
    u = np.array([user.get(t, 0.0) for t in RIASEC_TYPES], dtype=np.float64)
    c = np.array([course.get(t, 0.0) for t in RIASEC_TYPES], dtype=np.float64)
    u, c = u - u.mean(), c - c.mean()
    nu, nc = np.linalg.norm(u), np.linalg.norm(c)
    if nu < 1e-9 or nc < 1e-9:
        return None
    return float((u @ c / (nu * nc) + 1) / 2)


def profile_is_flat(user, tolerance=0.05):
    values = [user.get(t, 0.0) for t in RIASEC_TYPES]
    return max(values) - min(values) < tolerance


def _minmax(values):
    lo, hi = float(np.min(values)), float(np.max(values))
    if hi - lo < 1e-9:
        return np.full_like(values, 0.5, dtype=np.float64)
    return (values - lo) / (hi - lo)


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

def rank_courses(query_vector, courses, vectors, weights, campus=None, nivel=None, limite=10,
                 riasec_user=None, riasec_courses=None, riasec_weight=0.5):
    """Ordena ofertas por texto, por perfil RIASEC ou pelos dois (híbrido).

    - Só texto (query_vector, sem riasec_user): score = similaridade de cosseno ponderada (comportamento original).
    - Só RIASEC (query_vector None): score = congruência 0..1 entre o perfil do estudante e o do curso.
    - Híbrido: cada componente é normalizado (mín-máx) entre as ofertas filtradas e combinado
      por riasec_weight. Assim nenhuma das escalas domina a outra.
    """
    if not courses:
        return []
    use_text = query_vector is not None
    use_riasec = bool(riasec_user) and riasec_courses is not None and not profile_is_flat(riasec_user)
    if not use_text and not use_riasec:
        raise ValueError('Informe um texto ou um perfil RIASEC com diferenciação entre os tipos.')
    selected = [i for i, c in enumerate(courses)
                if (not campus or campus == 'Todos' or c.get('campus') == campus)
                and (not nivel or nivel == 'Todos' or c.get('nivel') == nivel)]
    if not selected:
        return []

    similarities, text_totals = {}, None
    if use_text:
        query = np.asarray(query_vector, dtype=np.float32)
        if query.ndim != 1 or not np.all(np.isfinite(query)):
            raise ValueError('Embedding da consulta inválido.')
        for field in weights:
            matrix = np.asarray(vectors[field], dtype=np.float32)
            if matrix.ndim != 2 or matrix.shape[0] != len(courses) or matrix.shape[1] != query.size:
                raise ValueError(f'Embeddings inconsistentes para {field}.')
            similarities[field] = matrix[selected] @ query
        text_totals = np.asarray(sum(weights[field] * similarities[field] for field in weights), dtype=np.float64)

    riasec_scores = None
    if use_riasec:
        riasec_scores = np.array([
            congruence(riasec_user, riasec_courses.get(courses[i].get('id_perfil'), {})) or 0.0
            for i in selected], dtype=np.float64)

    if use_text and use_riasec:
        w = min(max(float(riasec_weight), 0.0), 1.0)
        totals = (1 - w) * _minmax(text_totals) + w * _minmax(riasec_scores)
        method = 'hibrido'
    elif use_riasec:
        totals, method = riasec_scores, 'riasec'
    else:
        totals, method = text_totals, 'texto'

    # Ordenação estável preserva a ordem original em empates.
    order = np.argsort(-totals, kind='stable')[:limite]
    results = []
    for position in order:
        course = courses[selected[int(position)]]
        item = {
            **{field: course.get(field) for field in (
                'id_oferta', 'id_perfil', 'nome', 'campus', 'nivel', 'duracao',
                'area_principal', 'descricao', 'interesses_relacionados',
                'habilidades_relacionadas', 'objetivos_profissionais',
                'areas_atuacao', 'dimensoes_vocacionais')},
            'score': round(float(totals[position]), 4),
            'metodo': method,
        }
        if use_text:
            breakdown = {
                field: {
                    'label': FIELD_LABELS[field],
                    'similaridade': round(float(similarities[field][position]), 4),
                    'peso': weight,
                    'contribuicao': round(float(similarities[field][position]) * weight, 4),
                } for field, weight in weights.items()
            }
            strongest = max(breakdown, key=lambda f: breakdown[f]['similaridade'])
            item.update(dimensao_mais_proxima=FIELD_LABELS[strongest], detalhamento=breakdown,
                        score_texto=round(float(text_totals[position]), 4))
        if use_riasec:
            course_profile = riasec_courses.get(course.get('id_perfil'), {})
            item.update(score_riasec=round(float(riasec_scores[position]), 4),
                        codigo_curso=holland_code(course_profile))
        results.append(item)
    return results
