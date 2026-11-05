# 🎓 Guia de Carreira IFS

**Sistema de recomendação de cursos do Instituto Federal de Sergipe (IFS) com inteligência artificial.**

O **Guia de Carreira IFS** auxilia estudantes na exploração de possibilidades acadêmicas e profissionais. Em uma interface simples, o estudante informa seu **nome** e descreve, com suas próprias palavras, seus **interesses, habilidades e objetivos**. O sistema compara essa descrição com os perfis dos cursos cadastrados e apresenta sugestões ordenadas pela similaridade semântica.

> **Projeto acadêmico.** As recomendações servem como apoio à reflexão e à escolha do estudante, e não substituem orientação educacional ou profissional.

## ✨ Funcionalidades

- **Formulário simplificado:** nome e um único campo de descrição livre do perfil do estudante.
- **Recomendação com IA:** análise de textos com *embeddings* e similaridade de cosseno ponderada.
- **Resultados explicáveis:** cursos sugeridos com informações de oferta e detalhamento das dimensões usadas na análise.
- **Painel de gestão:** acompanhamento dos registros e recomendações armazenados pelo sistema.
- **Identidade visual do IFS:** interface em tema claro, com o símbolo institucional.
- **API documentada:** endpoints disponíveis por meio da documentação interativa do FastAPI.

## 🧠 Como funciona a recomendação

1. O estudante descreve o que gosta, o que sabe fazer e o que deseja para o futuro.
2. O frontend envia a descrição ao backend **Django**.
3. O Django encaminha a consulta à API **FastAPI**.
4. A API transforma o texto em uma representação vetorial usando o modelo `paraphrase-multilingual-MiniLM-L12-v2` (*Sentence Transformers*).
5. A similaridade entre a descrição e os campos dos cursos é calculada e ponderada; os resultados são ordenados pela pontuação obtida.
6. A interface apresenta as recomendações e o sistema registra os dados pertinentes para acompanhamento na gestão.

A base atualmente carregada contém **46 ofertas**, correspondentes a **36 perfis de cursos**. As dimensões consideradas no cálculo são:

| Dimensão | Peso inicial |
| --- | ---: |
| Interesses relacionados | 35% |
| Habilidades relacionadas | 20% |
| Objetivos profissionais | 20% |
| Áreas de atuação | 15% |
| Descrição do curso | 7% |
| Dimensões vocacionais | 3% |

**Importante:** esses pesos são parâmetros iniciais do algoritmo e ainda precisam de validação empírica. A pontuação exibida é uma **medida de similaridade**, não uma probabilidade de acerto nem uma porcentagem cientificamente validada de compatibilidade vocacional.

## 🛠️ Tecnologias

| Camada | Tecnologias |
| --- | --- |
| Interface web | HTML, CSS e JavaScript |
| Backend da interface | Python, Django e Django REST Framework |
| Serviço de recomendação | Python e FastAPI |
| Processamento de linguagem natural | Sentence Transformers, modelo multilingual MiniLM |
| Persistência | SQLite |
| Execução dos serviços | Docker e Docker Compose |

## 📁 Estrutura do projeto

```text
.
├── docker-compose.yml             # Orquestra os serviços
├── guia_carreira_ifs/
│   ├── Dockerfile
│   ├── backend/                  # Projeto Django e endpoints da interface
│   │   └── core/
│   │       ├── views.py
│   │       └── static/           # Imagens do logo
│   ├── site/
│   │   ├── index.html            # Página do estudante
│   │   └── gestao.html           # Painel de gestão
│   ├── database/                 # Base SQLite
│   └── requirements.txt
├── recomendador_cursos_ifs/
│   ├── Dockerfile
│   ├── app/
│   │   └── main.py               # API FastAPI
│   ├── data/
│   │   └── cursos_ifs.json       # Dados dos cursos
│   └── requirements.txt
└── tests/                        # Testes estruturais
```

## 🚀 Como executar localmente

### Pré-requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado e em execução;
- Docker Compose (incluído nas versões atuais do Docker Desktop);
- Internet na primeira inicialização para baixar o modelo de linguagem.

### 1. Obtenha o projeto

Clone o repositório ou baixe seu ZIP e extraia os arquivos. Abra um terminal na **pasta raiz**, onde está o `docker-compose.yml`.

### 2. Inicie os serviços

```bash
docker compose up --build
```

A primeira inicialização pode levar mais tempo porque a API baixa o modelo de IA e prepara os vetores dos cursos. Aguarde a mensagem de inicialização concluída do serviço de recomendação.

### 3. Acesse o sistema

| Serviço | Endereço |
| --- | --- |
| Interface do estudante | http://localhost:8001 |
| Painel de gestão | http://localhost:8001/gestao/ |
| Documentação interativa da API | http://localhost:8000/docs |
| Verificação de saúde da API | http://localhost:8000/health |

> Os endereços `localhost` funcionam no computador que está executando os contêineres. O projeto está configurado para uso local.

### Parar os serviços

```bash
docker compose down
```

**Cuidado com os dados:** a pasta `guia_carreira_ifs/database/` contém o arquivo SQLite. Faça backup antes de substituir arquivos do projeto ou o banco de dados.

## 🔌 Endpoints principais

### API de recomendação (FastAPI — porta 8000)

| Método | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/health` | Estado da API e do modelo |
| `GET` | `/metadata` | Informações da base, campi e níveis |
| `POST` | `/recommend` | Recomendações a partir de uma descrição |

Exemplo de requisição ao recomendador:

```bash
curl -X POST http://localhost:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{"interesses":"Gosto de tecnologia, matemática e programação. Quero desenvolver sistemas.","limite":5}'
```

O corpo aceita `interesses` (obrigatório), `campus` e `nivel` (opcionais), além de `limite` (entre 1 e 46).

### Backend da interface (Django — porta 8001)

| Método | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/api/ia/metadata/` | Consulta os metadados da API pelo Django |
| `POST` | `/api/ia/recomendar/` | Encaminha a descrição do estudante ao recomendador |

O formulário web envia um campo `description` ao endpoint Django, que o adapta para o campo `interesses` esperado pela FastAPI. A integração evita que o navegador precise acessar diretamente o serviço de IA.

## 🧪 Testes e diagnóstico

Para executar os testes estruturais incluídos no projeto, a partir da raiz:

```bash
python -m unittest discover -s tests -v
```

Para verificar o estado dos contêineres e os registros de execução:

```bash
docker compose ps
docker compose logs --tail=100 interface
docker compose logs --tail=100 recomendador-cursos
```

Se a interface abrir antes de o modelo de IA terminar a inicialização, aguarde o carregamento do serviço `recomendador-cursos` e atualize a página.

## ⚙️ Configuração e observações

- A comunicação entre os contêineres utiliza a variável `IFS_IA_API_URL` definida no `docker-compose.yml`.
- O modelo de linguagem utiliza **CPU** e é armazenado em volume Docker para reaproveitamento nas próximas execuções.
- O **SQLite** armazena informações usadas pela interface e pelo painel de gestão.
- A configuração atual é de **desenvolvimento local**. Antes de uma publicação pública, é necessário revisar segredo do Django, `DEBUG`, hosts autorizados, autenticação, HTTPS, permissões, armazenamento de dados e requisitos da LGPD.

## 📌 Estado do projeto

**Protótipo acadêmico funcional para execução local**, com interface integrada ao serviço de recomendação. O desempenho e a adequação das sugestões devem ser avaliados com testes e participantes antes de qualquer uso institucional.

## 📄 Licença

A licença de distribuição ainda não foi definida. Caso o código seja disponibilizado publicamente para reutilização, adicione um arquivo `LICENSE` com os termos escolhidos pelos responsáveis pelo projeto.
