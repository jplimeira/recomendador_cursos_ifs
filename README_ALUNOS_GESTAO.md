# Cadastro, autenticação e gestão — IFS

## Executar

1. Copie `.env.example` para `.env` e configure uma senha administrativa longa e exclusiva em `GESTAO_PASSWORD`.
2. Execute `docker compose up -d --build`.
3. Abra `http://localhost:8000` para criar uma conta de estudante, entrar e consultar os cursos.
4. Abra `http://localhost:8000/gestao` para acessar a gestão com as credenciais do `.env`.
5. No painel, o botão de atualização e a atualização automática a cada 30 segundos consultam dados do SQLite. O CSV exporta consultas reais, inclusive nomes e emails: proteja os arquivos exportados.

## Dados e privacidade

- Cadastro: nome, email, hash da senha, data de criação e registro do aceite de privacidade.
- Consulta: estudante, data UTC, texto de interesses, filtros e até 10 resultados recomendados.
- Não coleta IP ou dados de dispositivo para a base de consultas. O acesso administrativo é separado por HTTP Basic.
- Consultas antigas, anteriores à identificação, continuam sem estudante associado.
- Estudantes podem consultar o próprio histórico e excluir conta e consultas vinculadas.
- Sessões expiram após 7 dias; o token aleatório é guardado como hash no SQLite e enviado ao navegador em cookie HttpOnly, SameSite=Strict. Em HTTPS, o cookie também é Secure.
- O banco fica no volume persistente `dados_gestao` do Docker; faça backups protegidos e configure retenção e acesso administrativo conforme política institucional.

## Antes de publicar na internet

**Esta é uma implementação inicial, não uma homologação LGPD ou de segurança.** É necessário implantar HTTPS obrigatório (incluindo a gestão), proxy reverso confiável, política de privacidade institucional completa (finalidade, base legal, retenção, direitos e contato do encarregado), fluxo de recuperação de senha e verificação de email, trilhas de auditoria e controle granular de acesso da gestão, além de testes de carga e de segurança. Não use dados reais de estudantes em ambiente público sem essas providências.

Para testes locais sem baixar o modelo, execute `pip install -r requirements-dev.txt` e `pytest -q`.
