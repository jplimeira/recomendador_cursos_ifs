# Recomendador semântico de cursos do IFS

Aplicação em Python para recomendar ofertas de cursos do IFS a partir de uma descrição de interesses em linguagem natural. Executa em CPU, com FastAPI e Sentence Transformers.

## Requisitos

- Docker Engine
- Docker Compose v2 (`docker compose`)
- Acesso à internet na primeira inicialização para baixar o modelo Hugging Face

## Estrutura

```text
recomendador_cursos_ifs/
├── app/
│   ├── main.py
│   └── index.html
├── data/
│   └── cursos_ifs.json
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Executar

No diretório do projeto:

```bash
docker compose up -d --build
```

Acompanhar a inicialização e o download do modelo:

```bash
docker compose logs -f recomendador-cursos
```

Acessar a interface:

```text
http://localhost:8000
```

Documentação interativa da API:

```text
http://localhost:8000/docs
```

Verificar a saúde:

```bash
curl http://localhost:8000/health
```

## Exemplo de chamada da API

```bash
curl -X POST http://localhost:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "interesses": "Tenho interesse em programação, inteligência artificial, análise de dados e desenvolvimento de soluções digitais.",
    "campus": "Todos",
    "nivel": "Todos",
    "limite": 10
  }'
```

Filtros aceitos:
- `campus`: nome de um campus ou `Todos`.
- `nivel`: `Técnico Subsequente`, `Graduação` ou `Todos`.
- `limite`: quantidade máxima de ofertas (1 a 46).

## Como funciona

1. Na inicialização, a aplicação lê `data/cursos_ifs.json`.
2. Baixa/carrega o modelo `paraphrase-multilingual-MiniLM-L12-v2` em CPU.
3. Gera e mantém em memória embeddings independentes para os campos de cada oferta.
4. Para cada consulta, gera somente o embedding do texto informado.
5. Calcula similaridade de cosseno por campo e aplica uma soma ponderada.

Pesos iniciais:

| Campo | Peso |
|---|---:|
| interesses_relacionados | 0,35 |
| habilidades_relacionadas | 0,20 |
| objetivos_profissionais | 0,20 |
| areas_atuacao | 0,15 |
| descricao | 0,07 |
| dimensoes_vocacionais | 0,03 |

Os pesos são parâmetros iniciais e devem ser calibrados com exemplos avaliados por especialistas.

## Interpretação do score

O `score` é uma medida de similaridade usada para ordenar os resultados. **Não é probabilidade nem percentual de compatibilidade.** Valores dependem do modelo, do texto e do conjunto de cursos; não estabeleça um limiar universal sem validação.

A aplicação retorna ofertas, não apenas perfis. Assim, um mesmo perfil pode aparecer em mais de um campus, pois cada `id_oferta` representa uma oferta distinta.

## Alterar os cursos

Substitua `data/cursos_ifs.json` pelo arquivo atualizado e recrie o container:

```bash
docker compose up -d --build
```

## Parar

```bash
docker compose down
```

Os arquivos do modelo permanecem no volume Docker `modelo_huggingface`, evitando novo download em reinicializações.

Para remover também o modelo baixado:

```bash
docker compose down -v
```

## Observações

- O processamento de embeddings é executado em CPU; nenhuma GPU é exigida.
- A primeira inicialização pode demorar por causa do download do modelo.
- Os embeddings das ofertas são calculados uma vez por inicialização e reutilizados nas consultas.
- A recomendação é uma ferramenta de apoio. A qualidade deve ser avaliada com um conjunto de exemplos de interesses e cursos considerados adequados.

## Melhorias da versão 1.1

- Classificação extraída para `app/scoring.py`, com operações vetorizadas NumPy e ordenação estável.
- Validação do catálogo (IDs duplicados e campos essenciais) na inicialização.
- Limite de duas inferências simultâneas por processo, configurável por `MAX_CONCURRENT_INFERENCES`. Quando ocupado, retorna HTTP 503 e `Retry-After: 2`.
- Entrada de interesses limitada a 2.000 caracteres; mantém o contrato JSON da API.
- Frontend tenta recarregar metadados até seis vezes, com intervalos progressivos e botão de nova tentativa.
- `/health` devolve HTTP 503 até o modelo estar pronto (o Docker detecta corretamente indisponibilidade).
- Contadores agregados por dia via SQLite, **desativados por padrão** (`ENABLE_ANONYMOUS_METRICS=true` habilita). Não armazenam texto da consulta, IP ou identidade. Para persistência em Docker, monte um volume em `/app/runtime`.
- Pesos originais preservados. Opcionalmente, configure `WEIGHTS_FILE=/app/config/weights.json` e monte o arquivo no contêiner. A soma dos pesos deve ser 1.
- `scripts/evaluate.py` calcula Recall@5 e MRR@5 a partir de julgamentos humanos, sem alterar os pesos automaticamente.

### Testes

```bash
pip install -r requirements-dev.txt
pytest -q
```

Os testes utilizam um modelo simulado e não precisam baixar os pesos do Hugging Face. A avaliação semântica real requer o modelo e um conjunto de consultas avaliadas por especialistas.

### Calibração futura

Crie `avaliacoes.json` com exemplos como:

```json
[{"interesses": "Quero trabalhar com programação", "relevantes": ["ID_REAL_DA_OFERTA"]}]
```

Substitua o ID de exemplo por um ID presente em `data/cursos_ifs.json`. Execute `python -m scripts.evaluate avaliacoes.json`. Compare as métricas de diferentes configurações antes de alterar os pesos em produção. O score continua sendo similaridade, **não porcentagem de compatibilidade**.

### Catálogo único

O arquivo duplicado `cursos_ifs.json` da raiz foi removido **apenas nesta versão atualizada**. A fonte utilizada pela aplicação continua sendo `data/cursos_ifs.json`, sem alterações no conteúdo das ofertas. O ZIP original enviado permanece intacto.
