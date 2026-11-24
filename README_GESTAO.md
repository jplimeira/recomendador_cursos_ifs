# Painel de Gestão IFS

## Inicialização

1. Copie `.env.example` para `.env` e substitua `GESTAO_PASSWORD` por uma senha forte.
2. Execute `docker compose up --build -d`.
3. Acesse `/`. Tudo fica numa única página com abas: estudantes usam **Entrar → Sou estudante**; gestores usam **Entrar → Sou gestor**.

## Dados reais

Cada nova recomendação registra data UTC, filtros, texto de interesses e até dez cursos retornados em SQLite persistente. Os relatórios e gráficos são calculados desses registros. Não existem dados fictícios, nomes ou identificadores pessoais. Antes de utilizar em produção, informe aos usuários que seus textos de interesses serão registrados e estabeleça uma política de retenção e exclusão em conformidade com a LGPD.

O painel não pode recuperar consultas anteriores à implantação. Os indicadores começam em zero. O ranking de cursos indica frequência de aparição nas recomendações, **não** demanda comprovada por novas ofertas. Os scores são similaridades, não percentuais de compatibilidade.

## Segurança

A gestão é protegida por login de gestor com sessão em cookie HttpOnly e SameSite=Strict (expira em 8 horas, com limite de tentativas). A API também aceita HTTP Basic para scripts. Use **HTTPS** em produção: sem ele, credenciais e cookies trafegam sem criptografia. Configure segredo forte e não exponha `.env` em repositórios. Para implantação institucional, recomenda-se autenticação federada e controles de acesso mais completos.
