# Painel de Gestão IFS

## Inicialização

1. Copie `.env.example` para `.env` e substitua `GESTAO_PASSWORD` por uma senha forte.
2. Execute `docker compose up --build -d`.
3. Acesse `/` para o recomendador e `/gestao` para a gestão. O navegador solicitará usuário e senha.

## Dados reais

Cada nova recomendação registra data UTC, filtros, texto de interesses e até dez cursos retornados em SQLite persistente. Os relatórios e gráficos são calculados desses registros. Não existem dados fictícios, nomes ou identificadores pessoais. Antes de utilizar em produção, informe aos usuários que seus textos de interesses serão registrados e estabeleça uma política de retenção e exclusão em conformidade com a LGPD.

O painel não pode recuperar consultas anteriores à implantação. Os indicadores começam em zero. O ranking de cursos indica frequência de aparição nas recomendações, **não** demanda comprovada por novas ofertas. Os scores são similaridades, não percentuais de compatibilidade.

## Segurança

A gestão é protegida por HTTP Basic. Use **HTTPS** em produção; HTTP Basic não criptografa credenciais sozinho. Configure segredo forte e não exponha `.env` em repositórios. Para implantação institucional, recomenda-se autenticação federada e controles de acesso mais completos.
