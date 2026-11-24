# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primário — futuros alunos:** pessoas de fora do Instituto Federal de Sergipe (IFS), muitas vezes concluindo o ensino médio, que ainda não sabem qual curso ou campus escolher. Descrevem seus interesses em linguagem natural e querem uma lista curta de ofertas para considerar na inscrição.
- **Secundário — gestores do IFS:** equipe de campus ou reitoria que usa a área de gestão (aba Gestão da interface) para entender os interesses declarados pelos estudantes e apoiar o planejamento de novas ofertas de cursos.

## Product Purpose

Ajudar futuros alunos a descobrir ofertas de cursos do IFS alinhadas aos seus interesses, habilidades e objetivos, a partir de um texto livre, sem exigir que conheçam de antemão o nome dos cursos. Para a gestão, transformar as consultas reais em indicadores de demanda que apoiem decisões sobre novas ofertas.

Sucesso: o estudante encontra ofertas relevantes entre as primeiras posições (medido por Recall@5 e MRR@5 com julgamentos de especialistas em `scripts/evaluate.py`), e os gestores conseguem ler tendências de interesse a partir dos registros.

## Positioning

Recomendação semântica por oferta (curso + campus + nível), não por palavra-chave: o texto do estudante é comparado por similaridade de embeddings com vários campos descritivos de cada oferta (interesses, habilidades, objetivos, áreas de atuação, descrição, dimensões vocacionais), com pesos explícitos e calibráveis.

## Operating Context

- Protótipo acadêmico. Usa o nome e o catálogo do IFS, mas **não é um sistema oficial do instituto**.
- Estudante: acessa `/`, cria conta (nome, email, senha, aceite de privacidade), descreve interesses, filtra por campus e nível, vê resultados e o próprio histórico, e pode excluir a conta.
- Interface única em `/` com abas por perfil (navegação por `#/rota`): visitante (Início, Entrar), estudante (Encontrar cursos, Perfil de interesses, Meu histórico, Sugerir curso, Minha conta) e gestor (Painel, Consultas, Cursos, Sugestões). Aluno e gestor podem estar conectados ao mesmo tempo.
- Inventário de interesses RIASEC (Holland): 30 atividades (5 por tipo) em escala de 1 a 5, com itens próprios do projeto no formato do O*NET Interest Profiler/IPIP, ainda não validados para a população brasileira. Gera o perfil do estudante (gráfico de radar e código de 3 letras). Apresentado como inventário para orientação educacional, não como teste psicológico.
- Recomendação em três modos: só texto (similaridade semântica), só perfil RIASEC (congruência por correlação entre perfis) ou híbrido (componentes normalizados e combinados pelo peso `RIASEC_WEIGHT`, padrão 0,5). Perfis sem diferenciação entre os tipos são ignorados. Os perfis RIASEC dos cursos ficam em `data/riasec_cursos.json`, derivados do texto `dimensoes_vocacionais` e revisáveis (O*NET OnLine, professores).
- Sugestões de novos cursos: o estudante indica um curso que o IFS deveria oferecer (nome, área, campus, nível e motivo), vê e apaga as próprias sugestões (até 10 por dia). A gestão vê o ranking dos cursos mais pedidos, agrupando grafias diferentes e indicando se o curso já existe no catálogo, além da lista completa e exportação CSV.
- Gestão: login de gestor por formulário com sessão em cookie HttpOnly (8 h); dashboard atualizado a cada 30 s e exportação CSV. `/gestao` redireciona para a aba; HTTP Basic segue aceito na API para scripts.
- Execução local via Docker Compose; modelo `paraphrase-multilingual-MiniLM-L12-v2` em CPU, baixado na primeira inicialização.

## Capabilities and Constraints

- Catálogo: 46 ofertas em `data/cursos_ifs.json`, 9 campi (Aracaju, Estância, Glória, Itabaiana, Lagarto, Propriá, Socorro, São Cristóvão, Tobias Barreto), níveis Técnico Subsequente e Graduação.
- Stack existente: FastAPI (`app/main.py`), página única `app/index.html` (HTML/CSS/JS sem framework), logo em `app/static/`, SQLite, NumPy.
- Entrada de interesses limitada a 2.000 caracteres; limite de 1 a 46 resultados; até duas inferências simultâneas (HTTP 503 com `Retry-After` quando ocupado); `/health` retorna 503 até o modelo carregar.
- **O score é similaridade, não probabilidade nem percentual de compatibilidade.** Nenhuma interface pode apresentá-lo como “% de match”.
- O ranking de cursos na gestão indica frequência de aparição nas recomendações, não demanda comprovada.
- Pendências declaradas antes de publicação na internet: HTTPS obrigatório, política de privacidade institucional completa (LGPD), recuperação de senha, verificação de email, auditoria e controle de acesso granular na gestão.

## Brand Commitments

- Idioma: português do Brasil em toda a interface.
- Nome atual: “Recomendador de Cursos do IFS”; painel: “Análise de Demandas e Recomendações de Novos Cursos”.
- Por ser protótipo acadêmico, não deve se apresentar como canal oficial do IFS nem reproduzir a identidade institucional como se fosse oficial.

## Evidence on Hand

- O catálogo concentra cursos Realista/Investigativo (8 perfis com código idêntico RI), o que limita a capacidade do RIASEC sozinho de diferenciar cursos; motivo da escolha pelo modo híbrido.

- Dados reais do catálogo de ofertas em `data/cursos_ifs.json`.
- Indicadores da gestão vêm apenas de consultas reais registradas no SQLite; começam em zero.
- Não existem depoimentos, métricas de uso, avaliações de especialistas ou resultados de calibração ainda. Não inventar nenhum deles.

## Product Principles

1. **Honestidade sobre o algoritmo:** a recomendação é apoio à decisão, não veredito; scores nunca viram percentuais.
2. **Linguagem do estudante primeiro:** o futuro aluno escreve como pensa, sem precisar conhecer a nomenclatura dos cursos.
3. **Privacidade explícita:** o estudante sabe o que é registrado e pode ver e apagar seus dados.
4. **Dados reais ou nada:** a gestão mostra só o que foi registrado, sem números fictícios.
5. **Oferta concreta:** cada resultado é um curso em um campus e nível específicos, algo em que se pode efetivamente se inscrever.

## Accessibility & Inclusion

Sem padrão formal definido (em aberto). e-MAG não é requisito enquanto o projeto não for oficial; dispositivos predominantes do público ainda não foram levantados.
