# MySQL e Railway ? servi?o ?nico

## Fluxo atual

GitHub Actions: validate ? production. Um ?nico upload da fonte validada ? API.
O railway.json executa `python -m scripts.db db:migrate` no pre-deploy: container
separado do processo HTTP, imagem nova, mesmas vari?veis e rede privada. Falha
impede ativa??o da nova API. O comando adquire GET_LOCK, executa Alembic upgrade
head, verifica a revis?o e libera o lock. N?o h? downgrade autom?tico.
A inicializa??o da API apenas verifica schema e inicia Uvicorn; n?o migra.
O deploy normal troca a vers?o da API ap?s o pre-deploy e o healthcheck.

`scripts/deploy_migrations.py` ? legado para um servi?o separado. N?O executar
com o ID da API: seu upload substituiria a API pelo sentinel. A prote??o de IDs
iguais permanece intencionalmente. O workflow atual n?o chama esse script.
N?o ? necess?rio criar servi?o de migrations, nem configurar promote.

## GitHub: Environment production

| Nome | Tipo | Valor |
|---|---|---|
| RAILWAY_TOKEN | Secret | Project token do projeto e environment production |
| RAILWAY_PROJECT_ID | Variable | UUID do projeto |
| RAILWAY_ENVIRONMENT_ID | Variable | UUID de production no Railway |
| RAILWAY_SERVICE_ID | Variable | UUID da API existente |
| RAILWAY_MIGRATIONS_SERVICE_ID | Variable | Mesmo UUID da API |
| BACKEND_PRODUCTION_URL | Variable | Origem HTTPS p?blica real da API, sem caminho |

Copiar IDs nas configura??es do Railway. O environment GitHub ? exatamente
`production`, n?o `ctrl-x-Api / production`. N?o cadastrar credenciais MySQL no
GitHub. Manter aprova??o de production e PRs manuais feature ? develop ? prod.
Somente push em prod dispara publica??o, ap?s CI. Autodeploy Git do Railway deve
estar desativado para evitar publica??o duplicada. Nenhuma configura??o remota
foi alterada nesta tarefa.

## Railway: Variables da API

Configura??o recomendada: refer?ncias aos valores do servi?o MySQL existente:

| Nome | Valor |
|---|---|
| MYSQLHOST | Host privado do MySQL, terminado em .railway.internal |
| MYSQLPORT | 3306 |
| MYSQLUSER | Usu?rio MySQL |
| MYSQLPASSWORD | Senha original, sem percent-encoding |
| MYSQLDATABASE | Banco existente |
| APP_ENV | production |
| SECRET_KEY | Segredo aleat?rio exclusivo, ao menos 32 caracteres |
| CORS_ORIGINS | Origem HTTPS exata do frontend, sem barra final |

Usar Add Reference no painel; n?o copiar valores para logs. MYSQL_URL pode
permanecer definido, mas as cinco vari?veis individuais completas t?m prefer?ncia
sobre ele. DATABASE_URL ? opcional; quando fornecido tem prefer?ncia sobre MYSQL*.
DB_* legadas continuam priorit?rias por compatibilidade; remover configura??es
DB_* antigas se a inten??o for usar MYSQL*. Grupos individuais parciais falham.

Preced?ncia: DB_* ? DATABASE_URL ? MYSQL* individuais ? MYSQL_URL.
API e Alembic compartilham DatabaseSettings. URLs mysql:// s?o normalizadas para
mysql+pymysql://. URL.create protege caracteres especiais nas credenciais
individuais; URLs prontas devem ter usu?rio/senha corretamente escapados.
N?o usar localhost ou proxy p?blico em produ??o. MySQL deve manter volume
persistente e backup; n?o recriar banco/volume. N?o definir CI=true no Railway.

## Valida??o segura, sem migration

Ap?s esta vers?o estar dispon?vel no container, abrir Railway SSH no servi?o da
API e environment corretos e executar:

```sh
python -m scripts.db db:status
python -m scripts.db db:status --require-current
```

O primeiro comando conecta, verifica MySQL 8.4 e informa revis?es/pend?ncias sem
alterar schema. O segundo falha se houver migrations pendentes. N?o imprime
credenciais. Confirmar no painel que as refer?ncias apontam para o banco desejado;
um schema na mesma revis?o n?o comprova identidade do banco.
`railway run` executa localmente e n?o coloca o computador na rede privada.

## Migration pontual sem publicar ou reiniciar API

Railway SSH permite executar no container ativo, com autoriza??o expl?cita:

```sh
python -m scripts.db db:migrate
```

Isso usa somente migrations j? contidas na imagem ativa. N?o serve para aplicar
arquivos novos de um release ainda n?o publicado. N?o usar upload do sentinel,
stamp, edi??o manual do container ou migra??o no start command. Para releases
novos usar o pre-deploy nativo. SSH requer servi?o ativo e acesso autorizado.

Antes de migration real: revisar altera??es e backup/restaura??o, assegurar
compatibilidade com a API antiga (expand/contract). DDL MySQL pode deixar estado
parcial em falha; investigar antes de repetir. O lock evita concorr?ncia entre
execu??es do comando, mas n?o torna DDL transacional nem evita bloqueios de tabelas.

## Frontend e verifica??o final

Configurar a URL real da API no contrato de ambiente do frontend e CORS_ORIGINS
na API. Endpoints usam /api/v1; /health deve retornar 200 com {"status":"ok"}.
Cookies s?o HttpOnly e SameSite=None, com Secure fora de development
(SameSite=Lax sem Secure em development), para permitir Vercel/Railway cross-site.
CORS e valida??o estrita de Origin continuam obrigat?rios. Se o navegador bloquear
cookies de terceiros, usar dom?nios pr?prios no mesmo site ou proxy de mesma origem.

## Refer?ncias

- https://docs.railway.com/deployments/pre-deploy-command
- https://docs.railway.com/cli/ssh
- https://docs.railway.com/cli


## Destino expl?cito e diagn?stico da CLI

O projeto de produ??o ? `ctrl-x-api`, ID
`d8bc085c-a818-413e-8233-3fabff1cde1f`. Configure tamb?m a vari?vel
`RAILWAY_SERVICE_NAME` no GitHub Environment `production`, com o nome atual
exato da API no painel Railway. O nome pode mudar; `RAILWAY_SERVICE_ID`
deve continuar sendo o UUID da API, nunca o UUID do servi?o `MySQL`.
O script confere o nome e o ID do servi?o e o ID/nome de `production` antes
que qualquer upload seja feito. O nome do projeto n?o ? o nome do servi?o.

A CLI permanece fixada em 5.74.0. O fluxo usa `railway status --project ...
--environment ... --json`, seguido de `railway up --project ... --service ...
--environment ... --detach --json`. O acompanhamento tamb?m informa o projeto.
N?o executa `railway link`, `whoami` ou login interativo.

`RAILWAY_TOKEN` deve conter um Project Token emitido para esse projeto e
ambiente production. Tokens de conta/workspace usam `RAILWAY_API_TOKEN` e
n?o devem ser colocados nesse secret. O workflow injeta o secret no ambiente
do Python; os subprocessos herdam o ambiente, sem token nos argumentos.
A exist?ncia/formato do valor n?o comprova seu tipo: a autentica??o real ?
verificada pela consulta de status antes do upload. Nunca publique o valor
para diagnosticar. Nenhum token remoto foi inspecionado nesta corre??o.

`railway link` consulta workspaces/identidade do usu?rio, o que pode falhar
com Project Tokens. O erro antigo ocultava stdout e stderr, portanto seu
exit code isolado n?o comprova a causa remota. Agora erros mostram apenas
linhas de diagn?stico filtradas, limitadas e com segredos/URLs removidos.

Sequ?ncia efetiva: CI ? upload/build ? Database Migrations (pre-deploy hook)
? ativa??o da API ? healthcheck. N?o h? job GitHub separado de migrations:
a imagem nova ? necess?ria para executar as migrations novas. Falha do hook
impede ativa??o e o script rejeita qualquer status terminal diferente de SUCCESS.
N?o executar o uploader legado de migrations no servi?o da API.

Refer?ncias: https://docs.railway.com/cli e
https://docs.railway.com/deployments/pre-deploy-command.


## Diagn?stico seguro do startup da API

O startup emite JSON em stderr com `event=api_startup`, `stage` e
`status=started|passed|failed`. Em falha inclui `error_type`, `code` e
`variables` (somente nomes, nunca valores ou texto da exce??o).
Use o primeiro evento `failed` para localizar a origem; etapas externas
podem registrar a propaga??o da mesma falha.

Etapas: `environment` (APP_ENV), `port` (PORT), `settings` (Pydantic,
SECRET_KEY e resolu??o do banco), `cors` (CORS_ORIGINS), `database_engine`
(URL/driver/host/porta/credenciais e cria??o do engine SQLAlchemy),
`database_connection`, `mysql_version` e `alembic_revision`.
A consulta de schema continua somente leitura: n?o executa Alembic upgrade.
Erros de conex?o e revis?o nunca imprimem mensagens de exce??o.

Na API Railway configure APP_ENV=production, SECRET_KEY exclusivo com pelo
menos 32 caracteres e CORS_ORIGINS com origens HTTPS expl?citas, separadas por
v?rgula, sem caminhos, credenciais ou barra final. PORT ? fornecido pelo Railway;
se definido manualmente deve ser inteiro entre 1 e 65535.

Para banco use MYSQLHOST, MYSQLPORT=3306, MYSQLUSER, MYSQLPASSWORD e
MYSQLDATABASE completos, referenciando o servi?o MySQL privado. Alternativamente,
DATABASE_URL deve conter usu?rio, senha, host *.railway.internal, porta expl?cita
3306 e nome do banco; mysql:// ? normalizado para mysql+pymysql://.
URLs precisam de escaping correto das credenciais. N?o copie a URL para logs.
DB_* legado tem preced?ncia sobre DATABASE_URL; DATABASE_URL tem preced?ncia
sobre MYSQL* e MYSQL_URL. Remova grupos legados parciais/obsoletos quando
pretender usar as refer?ncias MYSQL*. N?o configure CI=true no container.

Um ValueError isolado n?o permite determinar a configura??o remota incorreta.
Os c?digos production_database_private_host, production_database_port,
production_database_username, production_database_password,
production_database_database e production_database_driver distinguem as
restri??es da URL de produ??o. Erros Pydantic apontam os nomes de campos
inv?lidos ou o grupo incompleto, sem registrar input, msg ou ctx.
