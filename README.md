# Guia de Carreira IFS

Sistema web que recomenda ofertas de cursos do Instituto Federal de Sergipe (IFS) a partir dos interesses do estudante. Ele combina o que o estudante escreve com um inventário de interesses baseado no modelo RIASEC de Holland, explica por que cada curso apareceu e oferece à gestão um painel com a demanda real.

> **Projeto acadêmico** (Projeto Integrador II, Gestão da Tecnologia da Informação, IFS). Não é um canal oficial do IFS. As recomendações apoiam a reflexão do estudante e não substituem orientação educacional.

## Funcionalidades

**Para o estudante**
- Conta própria (nome, email e senha), com histórico e exclusão de todos os dados.
- **Perfil de interesses:** inventário de 30 atividades com gráfico de radar e código de Holland (ex.: IRC).
- **Encontrar cursos:** texto livre, perfil de interesses ou os dois combinados; filtros por campus e nível; explicação de cada resultado.
- **Aviso quando nenhum curso combina**, com atalho para sugerir o curso ao IFS.
- **Sugerir curso:** indica um curso que o IFS deveria oferecer e por quê.

**Para a gestão**
- Login próprio de gestor, separado do estudante.
- Painel com consultas por dia, áreas, campi, tipo de interesse predominante e buscas sem curso próximo.
- Abas Consultas, Cursos (mais recomendados) e Sugestões (cursos mais pedidos, indicando se já existem).
- Exportação CSV de consultas e sugestões.

Tudo funciona em uma única página com abas; cada pessoa vê as abas do seu perfil.

## Como executar

### Requisitos
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Docker Engine e Docker Compose v2) em execução.
- Internet na primeira inicialização, para baixar o modelo de linguagem (cerca de 460 MB, guardado em cache depois).

### 1. Configure a senha da gestão

Copie o arquivo de exemplo e troque a senha por uma senha forte. **Sem esse arquivo o sistema não inicia.**

```powershell
Copy-Item .env.example .env
```

No Linux ou macOS: `cp .env.example .env`. Depois edite o `.env`:

```text
GESTAO_USER=gestao
GESTAO_PASSWORD=uma-senha-longa-e-exclusiva
```

O `.env` não é enviado ao GitHub.

### 2. Suba o sistema

```bash
docker compose up -d --build
```

A primeira vez leva alguns minutos (instalação e download do modelo). Depois, cerca de 30 segundos.

### 3. Acesse

| Endereço | Para quê |
|---|---|
| http://localhost:8000 | Sistema (estudante e gestão) |
| http://localhost:8000/docs | Documentação interativa da API |
| http://localhost:8000/health | Situação do serviço (`"status":"ok"` quando pronto) |

Se a página disser que não conseguiu conectar, o sistema ainda está iniciando: aguarde alguns segundos.

### Comandos úteis

```bash
docker compose logs -f recomendador-cursos   # acompanhar a inicialização
docker compose down                          # desligar (os dados ficam guardados)
docker compose down -v                       # desligar e APAGAR dados e modelo baixado
```

## Como usar

**Estudante:** em **Entrar → Sou estudante → Criar conta**, crie a conta. Responda ao inventário em **Perfil de interesses** e use **Encontrar cursos**, com ou sem texto. Em **Sugerir curso**, indique cursos que o IFS não oferece.

**Gestor:** em **Entrar → Sou gestor**, use o usuário e a senha do `.env`. As abas Painel, Consultas, Cursos e Sugestões aparecem na barra. O endereço antigo `/gestao` leva para lá.

Estudante e gestor podem ficar conectados ao mesmo tempo no mesmo navegador; cada botão **Sair** aparece na sua área.

## Como funciona a recomendação

O catálogo (`data/cursos_ifs.json`) tem **46 ofertas** (36 perfis de curso em 9 campi, níveis Técnico Subsequente e Graduação). Ao iniciar, o sistema carrega o modelo `paraphrase-multilingual-MiniLM-L12-v2` em CPU e calcula os vetores de seis campos de cada oferta.

| Modo | Quando é usado | Como ordena |
|---|---|---|
| **Texto** | só a descrição | similaridade de cosseno ponderada entre o texto e os seis campos do curso |
| **Perfil (RIASEC)** | só o inventário | correlação entre o perfil do estudante e o do curso, de 0 a 1 |
| **Híbrido** (padrão) | texto + inventário | as duas pontuações normalizadas entre as ofertas e combinadas por `RIASEC_WEIGHT` (0,5) |

Pesos do modo texto: interesses 0,35 · habilidades 0,20 · objetivos 0,20 · áreas de atuação 0,15 · descrição 0,07 · dimensões vocacionais 0,03.

**Inventário RIASEC:** 30 atividades (5 por tipo: Realista, Investigativo, Artístico, Social, Empreendedor, Convencional) em escala de 1 a 5, em `data/riasec_itens.json`. Os itens foram elaborados para o projeto, no formato do O*NET Interest Profiler, e **não são validados para a população brasileira**. Por isso o recurso é apresentado como inventário de orientação, não como teste psicológico. Perfis sem diferenciação entre os tipos são ignorados.

**Perfis dos cursos:** `data/riasec_cursos.json`, gerados a partir do campo `dimensoes_vocacionais` do catálogo (1ª letra 1,0; 2ª 0,7; 3ª 0,5; "com componente" 0,4). Podem ser revisados manualmente; troque o campo `fonte` do curso revisado.

**Nenhum curso parecido:** se a melhor similaridade de texto ficar abaixo de `LOW_AFFINITY_THRESHOLD` (0,40), a interface avisa e convida a sugerir o curso. Valor observado com o modelo real: cursos pertinentes de 0,43 a 0,64; pedidos fora do catálogo (saúde, moda) de 0,27 a 0,37.

**O score não é porcentagem de compatibilidade nem probabilidade.** Ele serve só para ordenar as ofertas.

## Estrutura do projeto

```text
app/
  main.py               API, contas, sessões, inventário, sugestões e gestão
  scoring.py            cálculo da recomendação (texto, RIASEC e híbrido)
  index.html            interface única com abas
  static/logo-ifs.png
data/
  cursos_ifs.json       catálogo de ofertas (fonte usada pelo sistema)
  riasec_cursos.json    perfil RIASEC de cada curso
  riasec_itens.json     itens do inventário
config/weights.json     modelo para alterar os pesos do modo texto
scripts/
  evaluate.py           compara os modos com casos avaliados por especialistas
  gerar_riasec_cursos.py gera os perfis RIASEC a partir do catálogo
tests/                  testes automatizados (pytest)
docs/
  base_cursos_ifs_definitiva_banco_sistema.xlsx   planilha de origem do catálogo
  modelagem_banco_ifs_revisado.sql                modelagem relacional do catálogo
PRODUCT.md              contexto do produto (público, propósito, princípios)
```

Os dados de uso (contas, sessões, consultas, perfis e sugestões) ficam em SQLite, no volume Docker `dados_gestao`.

## Atualizar os cursos

1. Edite a planilha em `docs/` e atualize `data/cursos_ifs.json` com os mesmos dados.
2. Regenere os perfis RIASEC no seu computador (precisa de Python 3.11 e `pip install -r requirements-dev.txt`; perfis revisados manualmente são preservados):
   ```bash
   python -m scripts.gerar_riasec_cursos
   ```
3. Recrie o contêiner: `docker compose up -d --build`.

Na inicialização, o sistema valida o catálogo (IDs únicos e campos obrigatórios) e não sobe se houver erro.

## Configuração

| Variável | Padrão | Função |
|---|---|---|
| `GESTAO_USER` / `GESTAO_PASSWORD` | `gestao` / obrigatória | Credenciais da gestão (arquivo `.env`) |
| `RIASEC_WEIGHT` | `0.5` | Peso do perfil no modo híbrido (0 = só texto, 1 = só perfil) |
| `LOW_AFFINITY_THRESHOLD` | `0.40` | Abaixo disso, avisa que não há curso parecido |
| `WEIGHTS_FILE` | — | Arquivo JSON com outros pesos do modo texto (soma 1). No contêiner: edite `config/weights.json`, defina `WEIGHTS_FILE: /app/config/weights.json` no `docker-compose.yml` e reconstrua |
| `MAX_CONCURRENT_INFERENCES` | `2` | Recomendações simultâneas; acima disso responde 503 e pede nova tentativa |

## Testes e avaliação

Com Python 3.11 instalado:

```bash
pip install -r requirements-dev.txt
pytest -q
```

Os testes usam um modelo simulado: não instalam o PyTorch nem baixam o modelo real.

Para medir a qualidade, crie `avaliacoes.json` com casos avaliados por professores ou orientadores:

```json
[{"interesses": "Gosto do mar e de barcos", "riasec": {"R": 0.8, "I": 0.6, "A": 0.1, "S": 0.2, "E": 0.3, "C": 0.4},
  "relevantes": ["OFE-001"]}]
```

O campo `riasec` é opcional; use IDs reais de `data/cursos_ifs.json`. A avaliação precisa do modelo real, então roda dentro do contêiner (com o sistema ligado):

```bash
docker cp avaliacoes.json recomendador-cursos-ifs:/app/avaliacoes.json
docker exec recomendador-cursos-ifs python -m scripts.evaluate avaliacoes.json --pesos 0 0.25 0.5 0.75 1
```

O script mostra Recall@5 e MRR@5 dos modos texto, perfil e híbrido (com cada peso). Os pesos não são alterados automaticamente.

## Privacidade e segurança

- **Dados guardados:** nome, email, hash da senha, data do aceite de privacidade, texto e resultado das consultas, respostas do inventário e sugestões. Não são armazenados IP, dados do dispositivo, idade ou cidade (o IP é usado só na memória, por 15 minutos, para limitar tentativas de login).
- **Controle do estudante:** pode ver o histórico, apagar o perfil e as sugestões e excluir a conta com todos os dados.
- **Proteções:** senhas com PBKDF2-SHA256 (310 mil iterações); sessões em cookie HttpOnly e SameSite=Strict (7 dias para estudante, 8 horas para gestor); bloqueio após 8 tentativas de login em 15 minutos; exportações CSV protegidas contra fórmulas.
- **Antes de publicar na internet:** HTTPS obrigatório; política de privacidade conforme a LGPD (finalidade, base legal, retenção e encarregado); recuperação de senha e verificação de email; auditoria de acesso da gestão; testes de carga e de segurança. Os CSVs exportados contêm nomes e emails: proteja-os.

## Limitações conhecidas

- A qualidade das recomendações ainda não foi medida com especialistas; pesos e limites são valores iniciais.
- O catálogo concentra cursos Realistas e Investigativos (8 cursos com o mesmo código RI; Artístico só em um), o que limita o modo perfil sozinho.
- Textos muito curtos tendem a ter similaridade baixa e podem disparar o aviso de "nenhum curso parecido".

## Equipe

Antônio Oliveira de Santana e Jayro Pereira Limeira, com orientação de Fabrício Feitosa Carvalho.
Licença: ainda não definida.
