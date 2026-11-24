"""Gera data/riasec_cursos.json a partir do campo `dimensoes_vocacionais` do catálogo.

Conversão inicial (ponto de partida, deve ser revisada por especialistas ou pelo O*NET OnLine):
- 1ª letra citada: 1,0 · 2ª: 0,7 · 3ª: 0,5
- letra após "com componente": 0,4
- letras não citadas: 0,0

Uso: python -m scripts.gerar_riasec_cursos
Perfis já revisados manualmente (com "fonte" diferente de "derivado_do_texto") são preservados.
"""
import json
from pathlib import Path

from app.scoring import RIASEC_TYPES, parse_holland_text

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / 'data' / 'cursos_ifs.json'
OUTPUT = ROOT / 'data' / 'riasec_cursos.json'


def main():
    offers = json.loads(CATALOG.read_text(encoding='utf-8'))['ofertas']
    existing = {}
    if OUTPUT.exists():
        existing = json.loads(OUTPUT.read_text(encoding='utf-8')).get('perfis', {})
    profiles = {}
    for offer in offers:
        pid = offer['id_perfil']
        if pid in profiles:
            continue
        previous = existing.get(pid)
        if previous and previous.get('fonte') != 'derivado_do_texto':
            profiles[pid] = previous  # revisão manual: não sobrescrever
            continue
        vector = parse_holland_text(offer.get('dimensoes_vocacionais', ''))
        profiles[pid] = {
            'curso': offer['nome'],
            'texto_original': offer.get('dimensoes_vocacionais', ''),
            'vetor': {t: vector[t] for t in RIASEC_TYPES},
            'fonte': 'derivado_do_texto',
        }
    payload = {
        'descricao': 'Perfil RIASEC (0 a 1) de cada perfil de curso. Para revisar um curso, altere o vetor e troque '
                     '"fonte" para algo como "revisado_professores" ou "onet:<código da ocupação>".',
        'regra_conversao': '1ª letra 1,0; 2ª 0,7; 3ª 0,5; "com componente" 0,4; demais 0',
        'perfis': dict(sorted(profiles.items())),
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(profiles)} perfis gravados em {OUTPUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
