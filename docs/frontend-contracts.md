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
Reautenticar após expiração. Login limitado a cinco
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
O profissional também recebe `crefito_region`, `crefito_number` e
`verification_status`. Nome e CREFITO são editáveis; status não é entrada.
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
{"id":"00000000-0000-0000-0000-000000000001","user_id":"00000000-0000-0000-0000-000000000002","role":"PROFESSIONAL","full_name":"Profissional Fictício","crefito_region":3,"crefito_number":"12345-F","verification_status":"unverified"}
```

Todos os novos profissionais ficam `unverified`; legados têm CREFITO nulo até
completar perfil e também ficam `unverified`. Sem verificação confiável, aceite e
leitura profissional de pacientes retornam 403 `Professional verification required`.
Pedido para alvo não verificado retorna 404 `Professional not found`, assim como
alvo inexistente. Alterar nome ou CREFITO retira a verificação. Não exibir selo
por formato válido. Não há rota de verificação nesta entrega; a atuação clínica
fica bloqueada até implementar revisão confiável. Veja
[fontes, limitações e alternativa segura](crefito-verification.md).

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

## Próximos incrementos P0

Diário de dor, prontuários nativos com finalização e adendos e timeline
longitudinal ainda dependem de implementação. As rotas propostas estão em
`api-design.md`. A existência de vínculo profissional não concede acesso
automático a documentos.
