# Contratos implementados para o frontend

Todas as rotas abaixo usam `/api/v1`. JSON, UUIDs e datas ISO 8601 em UTC.
Enviar `credentials: "include"` em fetch e o Origin permitido nas mutações.
As respostas autenticadas possuem `Cache-Control: no-store`.

## Autenticação

| Método e rota | Entrada | Sucesso |
| --- | --- | --- |
| `POST /auth/register` | `email`, `password` (12–128 caracteres), `full_name`, `role`; profissional exige `crefito_region` e `crefito_number` | 201, `{id, email, role}` |
| `POST /auth/login` | `email`, `password` | 200, `{id, email, role}` e cookie `ctrlx_access` |
| `GET /auth/me` | Cookie | 200, `{id, email, role}` |
| `POST /auth/logout` | Cookie e Origin | 204, revoga sessão e remove cookie |

Cookie HttpOnly, host-only, SameSite=None e Secure fora de desenvolvimento;
development usa SameSite=Lax sem Secure. Validade de 900 segundos.
`POST /auth/login` e `GET /auth/me` expõem `X-Session-Remaining` ao frontend
com os segundos restantes da sessão. Consultar `/auth/me` não renova o prazo.
Na expiração ou ao receber 401 em uma sessão autenticada, o frontend descarta
o cache privado em memória e volta ao login. Login limitado a cinco
tentativas por conta em 300 segundos, com 429 e `Retry-After`.

## Perfis e vínculos

| Método e rota | Entrada | Sucesso |
| --- | --- | --- |
| `GET /me` | Cookie | 200, perfil próprio |
| `PATCH /me` | `{full_name}` | 200, perfil atualizado |
| `GET /patients/{patient_id}` | Cookie | 200, perfil do paciente próprio ou vinculado ativamente |
| `GET /patients` | Profissional; `limit` (1–100, padrão 20), `cursor` UUID opcional | 200, `{items, next_cursor}`, somente pacientes com vínculo ativo |
| `GET /me/professional-links` | `limit` (1–100, padrão 20), `cursor` UUID opcional | 200, `{items, next_cursor}` |
| `POST /me/professional-links` | Paciente envia `{professional_id}` | 201, vínculo pendente |
| `POST /me/professional-links/{link_id}/accept` | Profissional destinatário, sem corpo | 200, vínculo ativo |
| `POST /me/professional-links/{link_id}/reject` | Profissional destinatário; pedido pendente, sem corpo | 204, pedido recusado |
| `POST /me/professional-links/{link_id}/revoke` | Um dos participantes, sem corpo | 204, inclusive se já revogado |

Perfil tem `{id, user_id, role, full_name}`. `id` identifica o perfil de paciente
ou profissional. `user_id` identifica a conta e corresponde a `id` de `/auth/me`.
Usar o ID de perfil nos parâmetros `patient_id` e `professional_id`.
O profissional também recebe `crefito_region`, `crefito_number`,
`account_status` e `verification_status`. Nome e CREFITO são editáveis.
O paciente não pode enviar campos profissionais. Campos adicionais são rejeitados.

Novo cadastro `PROFESSIONAL` exige regional (inteiro 1–22) e número (string de
1–7 dígitos positivos, sufixo `-F` opcional). `0012345-f` normaliza para `12345-F`;
`-TO` é rejeitado. Isso valida formato, não habilitação. Cadastro de pacientes,
login, cookie e `/auth/me` mantêm seus contratos. Colisão de email ou CREFITO no
cadastro profissional retorna 409 `Unable to register with these details`.

```json
{"email":"synthetic-physio@example.test","password":"fake-password-123","full_name":"Profissional Fictício","role":"PROFESSIONAL","crefito_region":3,"crefito_number":"12345-F"}
```

`PATCH /me` continua exigindo `full_name`. Para completar/alterar CREFITO, envie
regional e número juntos, não nulos. Colisão retorna 409
`Unable to update profile with these details`, sem atualização parcial.
Exemplo de resposta profissional, com identificadores fictícios:

```json
{"id":"00000000-0000-0000-0000-000000000001","user_id":"00000000-0000-0000-0000-000000000002","role":"PROFESSIONAL","full_name":"Profissional Fictício","account_status":"active","crefito_region":3,"crefito_number":"12345-F","verification_status":"unverified"}
```

O CREFITO é declarado pelo profissional e passa por validação de formato.
A conta profissional fica ativa desde o cadastro. O perfil retorna
`account_status: "active"` em `GET /me` e `PATCH /me`.
O aceite exige uma solicitação pendente destinada ao profissional. Leitura
de dados do paciente pelo profissional exige vínculo ativo.
`verification_status` é um campo legado de leitura que a interface pode ignorar.

Vínculo tem `{id, patient_id, professional_id, status, created_at, accepted_at,
revoked_at, closed_at}`. Status `pending`, `active`, `revoked`, `rejected` ou
`cancelled`. Datas de aceite e revogação
são nulas enquanto não ocorrerem. O paciente inicia o pedido, e o profissional
destinatário aceita. Criar pedido requer conhecer o UUID do profissional.
Uma busca pública de profissionais depende de contrato futuro.
Pedidos pendentes não liberam acesso. Existe no máximo um vínculo ativo por
paciente, inclusive sob concorrência. Sem vínculo ativo, pode haver pedidos
pendentes para vários profissionais. Criar pedido com vínculo ativo retorna 409;
o paciente deve encerrá-lo primeiro. Um aceite cancela atomicamente todos os
demais pedidos pendentes. Eles nunca voltam a liberar acesso: é necessário novo
pedido do paciente, inclusive após encerrar o vínculo atual.

`reject` recusa somente pedido pendente; outro estado retorna 409. `revoke`
preserva compatibilidade: em pendentes, cancela se o ator é paciente e recusa se
é o profissional; em ativos, encerra; em estados terminais, retorna 204 idempotente.
`closed_at` marca qualquer encerramento; `revoked_at` marca encerramento de ativo.
As recusas e cancelamentos anteriores à migration permanecem no histórico como
`revoked`, pois não é possível inferir sua intenção retroativamente.

A lista inclui apenas vínculos do usuário autenticado, ordenados por UUID,
com cursor exclusivo. Seguir `next_cursor` até ser nulo. IDs são imutáveis,
e a ordem por UUID não representa ordem cronológica.

## Erros

Formato `{detail: string}`. 401 requer login, 403 indica papel ou Origin
sem permissão, 404 cobre recurso inexistente ou fora do escopo do usuário,
409 indica conflito de estado, 422 indica payload/parâmetro inválido.
Erros de validação omitem os valores recebidos.

## Diário de dor

| Método e rota | Entrada | Sucesso |
| --- | --- | --- |
| `POST /me/pain-entries` | Paciente: `{region, intensity, description?, occurred_at?}` | 201, entrada persistida |
| `GET /me/pain-entries` | Paciente da sessão, com `limit`, `cursor`, `start`, `end` opcionais | 200, `{items, next_cursor}` |
| `PATCH /pain-entries/{entry_id}` | Paciente dono: subconjunto não vazio dos campos de criação | 200, entrada atualizada |
| `DELETE /pain-entries/{entry_id}` | Paciente dono; sem corpo | 204 |
| `GET /patients/{patient_id}/pain-entries` | Paciente dono ou profissional com vínculo ativo; `limit`, `cursor`, `start`, `end` opcionais | 200, `{items, next_cursor}` |

Entrada tem `{id, patient_id, region, intensity, description, occurred_at,
created_at, updated_at}`. IDs são UUIDs; `patient_id` vem da sessão na criação,
nunca do corpo enviado. `region` aceita 1–100 caracteres após remover espaços
externos; `intensity` é inteiro de 0 a 10 (booleanos, strings e frações são
rejeitados); `description` é opcional/nula e aceita até 2000 caracteres.
Campos adicionais são rejeitados. No PATCH, somente `description` aceita null;
campos omitidos preservam o valor atual. Exclusão remove a entrada, preservando
seu evento de auditoria, sem guardar o conteúdo clínico no evento.

`occurred_at` representa quando a dor ocorreu. Exige ISO 8601 com timezone;
quando omitido na criação, recebe o instante atual. Datas são normalizadas para
UTC e `occurred_at` tem precisão de segundos (frações são descartadas).
`created_at` e `updated_at` são controlados pelo servidor. Converta datas para o
fuso do paciente na interface.

Lista em ordem decrescente de `(occurred_at, id)`, com cursor exclusivo opaco;
`limit` de 1 a 100, padrão 20. Reenvie `next_cursor` como parâmetro URL usando
`URLSearchParams`, preservando os filtros; null encerra a paginação. `start`
inclui o instante inicial; `end` exclui o final. Ambos exigem timezone e, se
enviados juntos, `start < end`. Sem filtros, a consulta inclui todo o histórico,
sempre paginado. Alterações concorrentes de `occurred_at` podem mover entradas
entre páginas; recarregue a lista após editar.

```json
{"region":"Joelho esquerdo","intensity":5,"description":"Exemplo fictício","occurred_at":"2026-01-02T12:30:00-03:00"}
```

Profissionais nunca criam, editam ou excluem entradas, mesmo com vínculo ativo
(403). Leituras por profissionais exigem vínculo ativo em cada
requisição; pendência/revogação bloqueia acesso (404), sem apagar o diário.
Outro paciente recebe 404 para leitura, edição ou exclusão. Sessão ausente
retorna 401; mutações exigem Origin permitido, inclusive DELETE (CORS habilitado).
Respostas de sucesso usam `Cache-Control: no-store`.

## Linha do tempo, calendário e dashboard do paciente

| Endpoint | Parâmetros | Resposta |
| --- | --- | --- |
| `GET /me/timeline` | `month` (AAAA-MM) ou `date` (AAAA-MM-DD), `timezone` (IANA), `category`, `limit`, `cursor` | `{items, next_cursor}` |
| `GET /me/calendar` | `month` (AAAA-MM), `timezone` (IANA) | `{month, timezone, days, pain}` |

As rotas usam o paciente autenticado. Datas e meses começam à meia-noite
local e terminam antes da meia-noite seguinte ao período solicitado. Quando
omitido, `timezone` usa UTC. O frontend usa o fuso do navegador. Cada evento
de dor usa o UUID, a região, a intensidade e o instante UTC da entrada do
diário. O cursor é opaco e deve ser reenviado com o mesmo filtro. As
categorias `exercise` e `clinical_record` retornam lista vazia até que
essas fontes sejam integradas.

O calendário retorna apenas datas com registros, com `date` e
`pain_count`. O dashboard usa `pain.count`, `pain.average_intensity` e
`pain.latest_intensity` do mesmo mês. Em meses sem registros, a média e a
última intensidade são nulas. Uma intensidade registrada de zero é válida.

A migration `0007_pain_entries` cria a entidade e um índice por paciente/data/ID,
sem tabelas adicionais de timeline ou calendário. `care_audit_events` registra
`pain_entry_created`, `pain_entries_viewed`, `pain_entry_updated` e
`pain_entry_deleted`, contendo somente ator, paciente, recurso, ação e instante.
Frontend não faz parte desta entrega.

## Próximos incrementos P0

Prontuários nativos com finalização e adendos e timeline
longitudinal ainda dependem de implementação. As rotas propostas estão em
`api-design.md`. A existência de vínculo profissional não concede acesso
automático a documentos.
