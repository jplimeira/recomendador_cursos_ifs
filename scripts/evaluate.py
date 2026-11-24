"""Avalia rankings contra julgamentos humanos e compara os modos texto, RIASEC e híbrido.

Formato do arquivo (lista JSON):
  [{"interesses": "texto do estudante",
    "riasec": {"R": 0.8, "I": 0.6, "A": 0.1, "S": 0.2, "E": 0.3, "C": 0.5},   # opcional (0 a 1)
    "relevantes": ["OFE-001", "OFE-010"]}]

Em vez de "riasec", o caso pode trazer "respostas": {"R1": 5, "I1": 4, ...} do questionário.

Uso (com o modelo disponível):
  python -m scripts.evaluate avaliacoes.json
  python -m scripts.evaluate avaliacoes.json --pesos 0 0.25 0.5 0.75 1   # varre o peso do RIASEC
"""
import argparse
import json

import numpy as np

from app import main
from app.main import initialize_model_and_embeddings
from app.scoring import profile_from_answers, rank_courses


def case_profile(example):
    if example.get('riasec'):
        return example['riasec']
    if example.get('respostas'):
        q = main.riasec_questionnaire()
        values = [e['valor'] for e in q['escala']]
        return profile_from_answers(q['itens'], example['respostas'], min(values), max(values))
    return None


def evaluate(examples, k=5, mode='texto', riasec_weight=0.5):
    recalls, reciprocal_ranks, used = [], [], 0
    for example in examples:
        relevant = set(example['relevantes'])
        if not relevant:
            raise ValueError('Cada exemplo precisa de pelo menos uma oferta relevante.')
        profile = case_profile(example) if mode in ('riasec', 'hibrido') else None
        if mode in ('riasec', 'hibrido') and not profile:
            continue  # caso sem perfil não entra na comparação desse modo
        vector = None
        if mode in ('texto', 'hibrido'):
            vector = np.asarray(main.model.encode([example['interesses']], normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False)[0], dtype=np.float32)
        results = rank_courses(vector, main.courses, main.course_vectors, main.FIELD_WEIGHTS, limite=k,
                               riasec_user=profile, riasec_courses=main.riasec_course_profiles() if profile else None,
                               riasec_weight=riasec_weight)
        ids = [r['id_oferta'] for r in results]
        recalls.append(len(relevant.intersection(ids)) / len(relevant))
        reciprocal_ranks.append(next((1 / (i + 1) for i, id_ in enumerate(ids) if id_ in relevant), 0))
        used += 1
    if not used:
        return {'modo': mode, 'consultas': 0}
    return {'modo': mode, 'peso_riasec': riasec_weight if mode == 'hibrido' else None, 'consultas': used,
            f'recall@{k}': round(float(np.mean(recalls)), 4), f'mrr@{k}': round(float(np.mean(reciprocal_ranks)), 4)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Compara os modos de recomendação com julgamentos humanos.')
    parser.add_argument('arquivo')
    parser.add_argument('--k', type=int, default=5)
    parser.add_argument('--pesos', type=float, nargs='*', default=[main.RIASEC_WEIGHT],
                        help='pesos do RIASEC a testar no modo híbrido')
    args = parser.parse_args()
    with open(args.arquivo, encoding='utf-8') as file:
        examples = json.load(file)
    if not isinstance(examples, list) or not examples:
        raise SystemExit('O arquivo precisa conter uma lista não vazia de avaliações.')
    initialize_model_and_embeddings()
    report = [evaluate(examples, args.k, 'texto'), evaluate(examples, args.k, 'riasec')]
    report += [evaluate(examples, args.k, 'hibrido', w) for w in args.pesos]
    print(json.dumps(report, ensure_ascii=False, indent=2))
