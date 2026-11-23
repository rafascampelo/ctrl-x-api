# CREFITO: declaração e verificação

Nesta branch, o CREFITO informado passa por validação de formato. O vínculo
ativo autoriza o acesso ao paciente. O texto abaixo registra o histórico do
fluxo de conferência suspenso no produto.

Decisões aprovadas em 15/11/2026: MVP exclusivo para fisioterapeutas; nome,
regional e número do CREFITO obrigatórios em novos cadastros profissionais;
profissionais não verificados bloqueados para atuação clínica. Validação de
formato e duplicidade não prova existência, titularidade ou regularidade.

## Fontes oficiais pesquisadas

Pesquisa em 15/11/2026, sem consultar registros de pessoas reais:

- [Consulta do CREFITO-3](https://www.crefito3.org.br/dsn/consultapf/buscas.html):
  formulário regional para fisioterapeutas e terapeutas ocupacionais de SP.
- [Carta de Serviços do CREFITO-19, seção 1.2](https://crefito19.org.br/cr19/wp-content/uploads/2026/02/Carta_de_Servicos_CREFITO_19_2026.pdf):
  consulta de inscrição ativa que exige desafio “não sou um robô”.
- [FAQ oficial do CREFITO-3](https://sites.google.com/crefito3.org.br/faq/exerc%C3%ADcio-profissional):
  exemplo de identificação `CREFITO-3 / 1111111-F`.
- [Resolução COFFITO 642/2025](https://www.coffito.gov.br/nsite/wp-content/uploads/2025/12/resolucao-642.pdf):
  criação do CREFITO-22. O limite 1–22 adotado é uma regra local de formato;
  não comprova operação do regional nem validade de inscrição.
- [CREFITO-2: consulta nacional de RQE](https://crefito2.gov.br/home/conteudo/coffito_libera_ferramenta_para_consultar_o_novo_rqe_e_lista_de_especialistas_em_fisioterapia_e_terapia_ocupacional_7272):
  qualificação de especialista não substitui o registro profissional de base.

Não foi encontrada nas fontes pesquisadas documentação pública de API nacional
de habilitação com contrato utilizável pelo Ctrl X. Isso não prova inexistência
de serviço ou de possibilidade de acordo institucional. Formulários distintos e
desafios antiautomação não constituem contrato de integração. Não há scraping,
contorno de desafios, endpoints presumidos ou consultas externas no cadastro.

## Alternativa segura proposta

Obter canal oficial de integração ou definir revisão operacional restrita:
conferir identidade, categoria fisioterapeuta, regional, número e situação junto
à fonte competente. Registrar fonte, evidência mínima protegida, responsável
autorizado e data. Definir validade, revalidação, revogação e contestação de
CREFITO declarado por outra conta. Encontrar um número não prova que o
solicitante seja seu titular; documentos enviados exigem autenticação na fonte.

O fluxo de comprovação de titularidade ainda precisa ser definido.
Não usar UPDATE manual como atalho de liberação de contas reais. O procedimento
e seus controles precisam ser aprovados antes de sua implementação.

## Conferência pública do CREFITO-3

O cadastro e a edição dos dados profissionais criam uma solicitação. O
operador autorizado consulta a inscrição no formulário público de São Paulo.
As demais regionais recebem `needs_review`. Uma falha no portal deixa a
solicitação pendente para nova tentativa.

Use estes comandos em um terminal privado com acesso operacional ao banco.
Use como `REVIEWER_UUID` o identificador interno atribuído ao operador. O
comando `show` exibe a inscrição necessária à consulta.

```text
python -m scripts.review_crefito pending
python -m scripts.review_crefito show REVIEW_UUID
python -m scripts.review_crefito record REVIEW_UUID active --reviewer-id REVIEWER_UUID
```

Confira a regional, o número e a categoria de fisioterapeuta. Registre `active`
ou `cancelled` quando a fonte mostrar essa situação explicitamente, `not_found`
quando a fonte confirmar a ausência da inscrição, ou `needs_review` quando a
resposta for ambígua. O banco guarda o identificador da solicitação, o operador,
a fonte, a data UTC e o resultado. O acesso operacional ao banco define quem
pode registrar resultados. Um resultado só pode ser registrado uma vez e
somente para a versão atual do cadastro.

Teste o fluxo com dados sintéticos localmente. Em uma conferência de produção,
use uma inscrição de teste disponibilizada pelo conselho ou do próprio titular
participando do teste. A conta de teste começa sem autorização clínica.

## Autorização clínica

Todos os novos cadastros e contas legadas ficam `unverified`. Não há transição
de produção para `verified` nesta entrega. `verified_at` e
`verification_reference` são internos, reservados para confirmação futura;
uma constraint exige ambos para `verified`. Não são entradas nem saídas públicas.
Testes usam evidências sintéticas, exclusivamente no banco isolado, para
exercitar o acesso após uma futura revisão confiável.

Profissional não verificado não recebe/aceita novos vínculos nem lê pacientes,
mesmo por vínculo ativo preexistente. Pode completar o próprio perfil, consultar
histórico, recusar e encerrar vínculos. Alterar nome ou CREFITO retira verificação.
Nenhum endpoint permite autoverificação. O produto fica bloqueado para atuação
clínica até a implementação de um processo confiável.

Contas antigas mantêm nome, IDs, autoria, histórico e sessões. CREFITO permanece
nulo até completar o perfil; a migration não inventa inscrições. A unicidade usa
`(crefito_region, crefito_number)` normalizado. Colisão retorna 409 genérico sem
revelar o titular. Isso impede duplicidade local, mas não comprova titularidade.
