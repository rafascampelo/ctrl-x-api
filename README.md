# Ctrl X Backend

## Diário de dor

API implementada com entradas persistidas por paciente, intensidade 0–10,
região, descrição opcional e instante UTC. Paciente pode criar, editar e excluir;
profissional verificado pode ler somente com vínculo ativo. Histórico paginado
com filtros por período, auditoria sem conteúdo clínico e migration
`0007_pain_entries`. Veja [contrato HTTP](docs/frontend-contracts.md#diário-de-dor).
Formulário e histórico do frontend ficam para uma entrega posterior.

## Perfis e vínculos profissionais

O incremento P0 de perfis e vínculos está implementado. Os contratos para o
frontend estão em [docs/frontend-contracts.md](docs/frontend-contracts.md).
O MVP profissional é exclusivo para fisioterapeutas e exige CREFITO no cadastro.
Formato válido não verifica habilitação. Profissionais não verificados ficam
bloqueados para atuação clínica, inclusive por vínculos preexistentes.
Esta entrega não promove contas a verificadas: a integração/revisão confiável
ainda precisa ser definida. Veja [pesquisa e limitações](docs/crefito-verification.md).
A migration `0004_professional_links` adiciona consentimento, histórico de vínculos,
restrição atômica de um profissional ativo por paciente e auditoria de acesso.
`0005_professional_crefito` adiciona CREFITO declarado único e status protegido;
`0006_link_decisions` distingue recusa/cancelamento e preserva datas históricas.
O aceite cancela demais pedidos pendentes na mesma transação. A troca exige
encerramento do vínculo ativo e nova solicitação do paciente.

`GET /api/v1/patients` lista, com paginação por cursor, somente pacientes com
vínculo ativo com o profissional autenticado. Solicitações pendentes e vínculos
revogados não aparecem. A resposta contém apenas o perfil básico, sem dados clínicos.

## Autenticação — CX-01

Configure `DATABASE_URL`, `SECRET_KEY` aleatória (mínimo 32 caracteres),
`JWT_ISSUER`, `JWT_AUDIENCE` e `CORS_ORIGINS` (origens completas e explícitas
separadas por vírgula). API e CORS leem `.env` via pydantic-settings. Alembic
lê `DATABASE_URL` do ambiente do processo. Execute as migrations antes da API.
Defina `APP_ENV=production` e use HTTPS em produção.

### Contrato HTTP

Todos os POST de autenticação exigem `Origin` exatamente igual a uma origem de
`CORS_ORIGINS`, inclusive clientes de linha de comando. Origin ausente, `null`
ou não autorizado retorna 403 com `{"detail":"Untrusted origin"}`. Payloads
inválidos retornam 422 com `{"detail":"Invalid request payload"}`. As respostas
de usuário contêm `id` (UUID), `email` normalizado e `role`.
O contrato também está disponível em `/openapi.json` e `/docs`.

| Endpoint | Corpo JSON | Resposta |
| --- | --- | --- |
| `POST /api/v1/auth/register` | `email`, `password`, `full_name`, `role`; profissional exige `crefito_region` e `crefito_number` | 201 com usuário. Duplicidade retorna 409; paciente recebe `Unable to register with this email`, profissional recebe `Unable to register with these details`. |
| `POST /api/v1/auth/login` | `email`, `password` | 200 com usuário e cookie. Credenciais incorretas retornam 401 com `{"detail":"Invalid credentials"}`. Limite atingido retorna 429 com `{"detail":"Too many login attempts"}` e `Retry-After` em segundos. |
| `GET /api/v1/auth/me` | — | 200 com usuário da sessão. Cookie ausente, JWT inválido, expirado ou sessão revogada retornam 401 com `{"detail":"Not authenticated"}`. |
| `POST /api/v1/auth/logout` | — | 204 sem corpo, revoga a sessão e remove o cookie. Idempotente, retorna 204 também para cookie ausente, inválido, expirado ou revogado. |

Registro aceita `PATIENT` ou `PROFESSIONAL`, senha de 12 a 128 caracteres e nome
de 1 a 200 caracteres após remoção de espaços externos. Email é normalizado
para minúsculas. Campos extras retornam 422.

```json
{"email":"person@example.test","password":"fake-password-123","full_name":"Fake Person","role":"PATIENT"}
```

### Sessão, cookies e frontend

Login emite `ctrlx_access=<JWT>; HttpOnly; Path=/; Max-Age=900; SameSite=None`.
`Secure` é adicionado em todo ambiente diferente de `development`; o modo
`development` usa `SameSite=Lax` sem `Secure`. Cookie é host-only, sem `Domain`.
Logout usa os mesmos atributos e `Max-Age=0`, com
`Expires` no passado. Login, `/me` e logout retornam `Cache-Control: no-store`.
JWT HS256 exige `sub`, `jti`, `iat`, `exp`, `iss` e `aud`. Expira após 15 minutos,
sem refresh ou renovação deslizante. Cada requisição autenticada consulta a
sessão persistida, seu proprietário, expiração UTC e revogação. Logout afeta
somente a sessão apresentada. Reutilizar seu JWT ainda não expirado retorna
401. JWTs anteriores à migration de sessões exigem novo login.

No frontend use `fetch(url, {credentials: "include", ...})`, inclusive em login,
`/me` e logout, e `Content-Type: application/json` ao enviar JSON. O navegador
adiciona `Origin`. Ao receber 401, solicite novo login. Tokens permanecem no
cookie HttpOnly. CORS permite GET/POST/PATCH/DELETE e Content-Type com credenciais apenas
para as origens configuradas, e expõe `Retry-After` ao frontend.

O modo de produção usa `SameSite=None; Secure` para permitir cookies entre os
domínios padrão `*.vercel.app` e `*.railway.app`. CORS com credenciais e a
validação estrita de Origin nas mutações continuam obrigatórios. Se o navegador
bloquear cookies de terceiros, use domínios próprios no mesmo site ou um proxy
de mesma origem. Em desenvolvimento use `localhost` em ambos os serviços.

A proteção CSRF combina validação estrita de Origin nas mutações de
autenticação, SameSite e CORS explícito. A dependência `current_user`
também exige Origin em métodos mutáveis. Referências da revisão de segurança
estão na [OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
e na [MDN](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch).

### Limitação e auditoria

Cada email normalizado admite 5 tentativas por janela fixa de 300 segundos,
iniciada na primeira tentativa. Tentativas bem-sucedidas também contam. A sexta
retorna 429 mesmo com senha correta. Pedidos bloqueados preservam o fim da
janela. O primeiro pedido após a janela pode tentar novamente. Contas
inexistentes seguem a mesma regra. MySQL usa upsert e bloqueio de linha em
transação para reservar cada tentativa antes de verificar a senha. Todas as
instâncias devem compartilhar banco e SECRET_KEY. A chave persistida é
HMAC-SHA256 do email. O limite por conta permite bloqueio temporário provocado
por terceiros. Proteção contra ataques distribuídos por muitas contas permanece
pendente.

O início da janela usa precisão de segundos, alinhada ao `DATETIME` do MySQL,
com descarte explícito dos microssegundos antes de persistir. Isso evita que
arredondamento do banco produza `Retry-After: 301`. O relógio é atualizado após
obter o bloqueio, e o cabeçalho fica entre 1 e 300 segundos, inclusive para
linhas antigas que tenham sido arredondadas para o segundo seguinte.

`auth_events` persiste `register_succeeded`, `register_rejected`, `login_failed`,
`login_blocked`, `login_succeeded`, `session_viewed`, `logout_succeeded` e
`logout_anonymous`, contendo UUID do evento, ação, UUID do usuário quando
aplicável e instante UTC. Eventos de falha de login omitem o usuário. A auditoria
omite credenciais, tokens, email, IP e conteúdos clínicos. Sessões, limites e
auditoria persistem após reinício. Política de retenção e limpeza está pendente.

## Fluxo de desenvolvimento

Fluxo obrigatório: `feature/<nome-em-kebab-case>` → PR para `develop` → PR de
`develop` para `prod`. Para cada mudança, crie uma branch específica a partir da
`develop` atualizada antes de editar arquivos. Nunca trabalhe diretamente em
`develop` ou `prod`; não faça push ou merge sem autorização explícita. Somente
push em `prod`, após CI e aprovação do Environment `production`, pode publicar.
Branches feature e `develop` executam CI sem deploy.

Commits aceitos: `feat`, `fix`, `refactor` ou `tests`, seguidos por uma descrição
curta, imperativa e em inglês, por exemplo `feat: add clinical record form`.
Consulte [CONTRIBUTING.md](CONTRIBUTING.md) antes de iniciar uma mudança.

## Visão do produto

Ctrl X é uma aplicação web responsiva, acessível pelo navegador em desktop,
tablet e celular. O frontend Next.js é publicado na Vercel e a API FastAPI
no Railway.

Pipeline do backend: [CI-CD.md](CI-CD.md). PRs e `develop` executam somente CI;
push em `prod` publica via Railway apenas após CI e proteção do Environment.
O deploy usa `.github/workflows/deploy-production.yml` e `railway.json`, com
Alembic no job `database-migrations`, executado no serviço privado
`ctrl-x-migrations` antes do job da API. O pre-deploy da API e cada réplica
apenas verificam o schema. Comandos e ativação: [migrations](docs/database-migrations.md).
PRs e merges de feature → develop → prod são manuais, com checks e revisões.
Os rulesets em `.github/rulesets/` precisam ser importados/ativados no GitHub
para bloquear pushes diretos. Secrets, revisores e serviços Railway ainda
exigem configuração manual autorizada; os arquivos locais não alteram essas contas.
As migrações agora estão inicializadas; defina `DATABASE_URL` antes de executar
`python -m alembic upgrade head`. `0002_users` cria usuários e perfis;
`0003_auth_state` cria sessões, limites e auditoria.

## Preparação da base

O desenho inicial está em [docs/architecture.md](docs/architecture.md) e
[docs/api-design.md](docs/api-design.md). As pastas por camada estão reservadas;
a API implementa `/health` e autenticação. O Alembic mantém migrations
versionadas e a CI valida upgrade, drift e downgrade em MySQL 8.4 isolado.

Alternativa de preparação com uv (sem ativar o ambiente):

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.lock
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

As dependências Python de OCR não instalam o executável Tesseract. Docker Desktop
e Tesseract são instalações separadas no Windows. A autenticação usa SQLAlchemy
e MySQL. O processamento de documentos será implementado posteriormente.

## Prerequisites (Windows)
- Python 3.12+, Docker Desktop with Linux containers / Compose v2
- Tesseract OCR installed on Windows, with Portuguese (`por`) and English (`eng`) language data

## Local setup (PowerShell)
```powershell
Copy-Item .env.example .env
# Edit .env and replace CHANGE_ME, CHANGE_ROOT_ME, SECRET_KEY with strong unique values.
docker compose up -d
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
$env:DATABASE_URL = "mysql+pymysql://ctrlx:<senha-local>@127.0.0.1:3307/ctrlx?charset=utf8mb4"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs.

Run tests in a separate activated PowerShell session:
```powershell
python -m pytest
python -m ruff check .
```

Tesseract check:
```powershell
& 'C:\Program Files\Tesseract-OCR\tesseract.exe' --list-langs
```

The development MySQL service is bound to `127.0.0.1:3307` (container 3306).
O Compose cria o banco `ctrlx` e seu usuário na primeira inicialização do volume
`mysql_data`. Alembic cria `alembic_version`, `users`, `patients`, `professionals`,
`auth_sessions`, `login_limits` e `auth_events`. Alterar MYSQL_* após inicializar
o volume exige administrar o banco existente. Preserve o volume para manter os
dados locais. Alembic lê `DATABASE_URL` do ambiente do processo.

O Compose inicia somente MySQL. O Dockerfile da API usa Python 3.12 slim,
dependências travadas, Tesseract por/eng, usuário sem privilégios, healthcheck e
Uvicorn com access log desabilitado. Build local usa
`docker build -t ctrlx-backend:local .`. Execute migrations separadamente antes
de iniciar a API. `.env` é local e os testes usam dados sintéticos.

## Validação local da CX-01

Use `.\.venv\Scripts\python.exe -m ruff check .` e
`.\.venv\Scripts\python.exe -m pytest`. Sem `TEST_DATABASE_URL`, os testes HTTP
usam SQLite em memória e os testes específicos de MySQL são pulados.

Para integração real, prepare MySQL **8.4** descartável em `127.0.0.1:3306`, banco
e usuário `ctrlx_ci`. Defina `DATABASE_URL` e `TEST_DATABASE_URL` com o mesmo
`mysql+pymysql://ctrlx_ci:<senha-de-teste>@127.0.0.1:3306/ctrlx_ci` e execute
com o Python do ambiente virtual.

```powershell
python -m scripts.ci_database
python -m alembic upgrade head
python -m alembic check
python -m alembic downgrade base
python -m alembic upgrade head
python -m alembic check
python -m pytest tests/integration -v
python -m pytest
```

Esse downgrade destina-se exclusivamente ao banco descartável de testes.
O teste concorrente reserva tentativas por conexões independentes para verificar
o bloqueio entre instâncias. Consulte [CI-CD.md](CI-CD.md) para a configuração
da CI. A validação MySQL e o build Docker dependem do daemon local.

Em 15/11/2026, migrations e testes de integração foram executados em MySQL
8.4.13 descartável. Como o Windows bloqueou a porta 3306, o executor Python
compartilhou a rede do container MySQL, preservando a identidade isolada
`127.0.0.1:3306/ctrlx_ci`. Build e smoke test da imagem de produção permanecem
pendentes.
