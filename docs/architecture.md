# Base do backend

Status atual inclui autenticação, perfis próprios, vínculos consentidos, leitura
autorizada de pacientes e diário de dor persistido. Consulte `frontend-contracts.md`
para as rotas implementadas.
As demais seções descrevem a evolução prevista do P0.

## Produto e implantação

Ctrl X é uma aplicação web responsiva acessada pelo navegador em desktop,
tablet e celular. O frontend Next.js é publicado na Vercel; esta API FastAPI
é publicada no Railway. O backend fornece os contratos e dados clínicos
autorizados ao frontend, sem duplicar as fontes de informação.

## Stack

- Python 3.12 como versão inicial do ambiente local.
- FastAPI e Uvicorn para HTTP; Pydantic Settings para configuração.
- SQLAlchemy 2 com PyMySQL (acesso síncrono) e transações explícitas.
- MySQL 8.4 em Docker Compose, acessível localmente na porta 3307.
- Alembic para todas as alterações de esquema.
- Argon2 via pwdlib e PyJWT para a futura autenticação.
- pytest, HTTPX e Ruff para testes e análise estática.
- As dependências de documentos/OCR já previstas permanecem preparadas;
  Tesseract e processamento OCR ficam para a etapa de documentos.

## Pastas e responsabilidades

| Pasta | Responsabilidade futura |
| --- | --- |
| `app/api/v1/endpoints` | Rotas, dependências HTTP e tradução de erros |
| `app/schemas` | Contratos de entrada e saída, sem HTML livre |
| `app/services` | Regras de negócio, autorização e limites de transações |
| `app/repositories` | Consultas e persistência, sem commit independente |
| `app/models` | Entidades e restrições SQLAlchemy |
| `app/core` | Configuração, segurança e auditoria |
| `app/db` | Engine, sessões e integração com metadados |
| `alembic/versions` | Migrações versionadas; baseline inicial sem tabelas de negócio |
| `tests/unit` | Validação e regras isoladas |
| `tests/integration` | HTTP, persistência, permissões e concorrência |

Fluxo previsto: HTTP → schemas → services → repositories → models/banco.
O serviço define a transação; repositórios não fazem commits por conta própria.
Diretórios vazios são marcados com `.gitkeep`; não são módulos implementados.

## Recursos e relações

Usuários têm identidade pública UUID e perfil paciente ou profissional. O vínculo
profissional liga essas identidades e mantém seu histórico. O banco deve garantir
atomicamente no máximo um vínculo ativo por paciente; a estratégia exata será
validada na primeira migração de vínculos contra MySQL, inclusive sob concorrência.
CPF é opcional e protegido, nunca chave primária ou informação de logs.

Prontuários clínicos, adendos, diário de dor, prescrições e registros de evolução
terão persistência própria e referências por paciente. Prescrições e evoluções
poderão referenciar avaliações quando houver um caso de uso concreto, sem criar
agora tabelas especulativas. Documentos e permissões de documentos são separados.
Timeline, dashboard e calendário serão consultas sobre essas fontes, sem cópias.

Prontuários terão patient_id, professional_id, status, complaint, anamnesis,
physical_assessment, body_region, pain_intensity (opcional, 0–10),
functional_limitations, therapeutic_goals, care_plan, notes, created_at,
updated_at e finalized_at. Finalização torna o registro imutável. Correções
serão adendos apenas de acréscimo com autor, data e motivo.

Datas serão tratadas em UTC com timezone na aplicação e conversão explícita na
fronteira do MySQL. A escolha do tipo SQL e sua serialização serão verificadas
na implementação da persistência.

## Limites de acesso

- Paciente acessa seus dados e edita seu diário; não altera prescrições.
- Profissional acessa dados clínicos somente com vínculo ativo; somente o autor
  com vínculo ativo pode editar rascunhos de seus prontuários.
- Revogação bloqueia acesso profissional futuro e preserva registros e autoria.
- Paciente pode ler seus prontuários; a visibilidade de rascunhos deve ser definida
  antes da implementação, sem pressupor acesso irrestrito a conteúdo em edição.
- Documentos exigem permissão explícita, além das verificações de identidade.
- Auditoria registra acessos e alterações sem conteúdo clínico, PII ou tokens.
- Uploads ficam em armazenamento privado, com nomes aleatórios e validação de
  tamanho, extensão, MIME e assinatura. OCR é texto não confiável para revisão.

## Ordem de implementação futura

1. Configuração, sessão SQLAlchemy e ambiente Alembic.
2. Identidade, autenticação e auditoria.
3. Vínculos com garantia atômica e testes de revogação/IDOR.
4. Prontuários nativos, finalização e adendos (prioridade P0).
5. Diário, prescrições e evolução; consultas de timeline/dashboard/calendário.
6. Documentos privados e OCR com revisão humana.

Cada incremento terá migração quando necessário e testes de sucesso, validação,
isolamento, ausência de autorização e acesso revogado. Nunca usar `create_all()`
como estratégia de migração de produção.
