"""Avalia rankings contra julgamentos humanos em arquivo JSON.
Formato: [{"interesses": "...", "relevantes": ["id_oferta", ...]}]
Executar com modelo disponível: python -m scripts.evaluate avaliacoes.json
"""
import json
import sys
import numpy as np
from app.main import initialize_model_and_embeddings
from app import main
from app.scoring import rank_courses

def evaluate(examples, k=5):
    recalls, reciprocal_ranks = [], []
    for example in examples:
        relevant = set(example['relevantes'])
        if not relevant:
            raise ValueError('Cada exemplo precisa de pelo menos uma oferta relevante.')
        vector = np.asarray(main.model.encode([example['interesses']], normalize_embeddings=True,
                            convert_to_numpy=True, show_progress_bar=False)[0], dtype=np.float32)
        results = rank_courses(vector, main.courses, main.course_vectors, main.FIELD_WEIGHTS, limite=k)
        ids = [r['id_oferta'] for r in results]
        recalls.append(len(relevant.intersection(ids)) / len(relevant))
        reciprocal_ranks.append(next((1 / (i + 1) for i, id_ in enumerate(ids) if id_ in relevant), 0))
    return {'consultas': len(examples), f'recall@{k}': round(float(np.mean(recalls)), 4),
            f'mrr@{k}': round(float(np.mean(reciprocal_ranks)), 4)}

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Uso: python -m scripts.evaluate avaliacoes.json')
    with open(sys.argv[1], encoding='utf-8') as file:
        examples = json.load(file)
    if not isinstance(examples, list) or not examples:
        raise SystemExit('O arquivo precisa conter uma lista não vazia de avaliações.')
    initialize_model_and_embeddings()
    print(json.dumps(evaluate(examples), ensure_ascii=False, indent=2))
