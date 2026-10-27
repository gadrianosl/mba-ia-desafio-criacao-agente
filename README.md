# Assistente virtual do Residencial Aurora

API Python com Google ADK 2.9.1 e Gemini para reservas de áreas comuns,
autorização de visitantes e consultas ao regulamento. A identidade do morador,
a confirmação de ações e a exclusividade das reservas são protegidas pelo código.

## Arquitetura

O [runtime](aurora/runtime.py), criado por `build_agent`, contém três agentes:

| Agente | Responsabilidade | Acionamento |
| --- | --- | --- |
| `principal` | Encaminhar o pedido ao especialista adequado. | Entrada da conversa ou retorno de um especialista. |
| `operacoes` | Consultar e cancelar reservas próprias, verificar disponibilidade, reservar e solicitar autorização de visitantes. | Transferência do principal. |
| `regulamento` | Responder dúvidas consultando artigos pertinentes ao assunto. | Transferência do principal. |

Os especialistas podem retornar ao principal; a transferência direta entre eles
está desabilitada. Essa separação mantém as tools de escrita no agente de
operações e a consulta de normas no especialista em regulamento. O principal
não recebe o documento do regulamento nas instruções.

As tools de operações são `listar_areas`, `minhas_reservas`, `meus_visitantes`,
`consultar_disponibilidade`, `reservar`, `cancelar_reserva` e
`autorizar_visitante`. Elas acessam o [armazenamento](aurora/storage.py), nunca
usam lembranças do modelo como fonte dos dados. A tool `consultar_regulamento`
usa a [busca local](aurora/regulations.py), normalizando acentos e selecionando
até dois artigos de um único capítulo. Consultas sem correspondência pedem
esclarecimento. A busca lexical pode exigir reformulação de perguntas vagas.

A [API FastAPI](aurora/api.py) chama o `Runner` do ADK e mantém dois bancos locais:

- `.local/runtime/business.sqlite3`: moradores, áreas, reservas, códigos históricos,
  visitantes, vínculo imutável de sessão e confirmações de negócio.
- `.local/runtime/sessions.sqlite3`: sessões e eventos completos do ADK, via
  `DatabaseSessionService`.

Nenhum banco externo ou container é necessário. Use um único worker de API por
diretório de runtime. As requisições de uma sessão são serializadas por um lock
no runtime; a exclusividade das reservas também é garantida pelo SQLite.

## Garantias

### 1. Cobrança ou acesso somente após confirmação

Em [Storage.reserve e Storage.authorize_visitor](aurora/storage.py), reservas
com taxa e autorizações de visitantes geram pendências, sem executar o efeito.
Reservas gratuitas são gravadas diretamente; cancelamentos próprios não pedem
confirmação.

Em [build_agent.finish_or_request](aurora/runtime.py), a tool chama
`ToolContext.request_confirmation` e o ADK gera `adk_request_confirmation`.
`Runtime.pending` relaciona esse evento à pendência de negócio. A resposta da
API inclui seu ID, ação e detalhes.

`Runtime.confirm` aceita somente um ID pendente daquela sessão e um booleano,
monta o `FunctionResponse` com o payload persistido e o entrega ao Runner. O
modelo não recebe uma tool de aprovação. Escrever uma aprovação no chat não
aciona esse método. A retomada executa `Storage.confirm`, que consome a pendência
e aplica a operação na mesma transação. Negação não cria reserva ou visitante;
reenvio sequencial é rejeitado com HTTP 409 pela API.

Uma negação encerra apenas aquela solicitação: um novo pedido cria outro ID e
exige outra aprovação. A configuração de transferência ao pai e a ausência de
`resumability_config` foram testadas no ADK 2.9.1 para devolver a confirmação ao
especialista correto com histórico persistido. Mudanças nessa topologia precisam
repetir os testes de retomada.

### 2. Sessão vinculada a um único apartamento

[Runtime.create_session](aurora/runtime.py) registra o apartamento por
`Storage.bind_session`. O trigger `immutable_session_apartment`, em
[Storage.__init__](aurora/storage.py), impede alterar esse vínculo.

As tools obtêm o ID de `tool_context.session.id`, sem argumento de apartamento.
`Storage._apartment` resolve a identidade, e as consultas filtram pelo apartamento
da sessão. `Storage.cancel` inclui `apartment=?` no `UPDATE`, impedindo cancelar
uma reserva de outro morador. A confirmação também resolve a identidade da
sessão no momento da execução.

`consultar_disponibilidade` retorna apenas um booleano. As leituras administrativas
`verification_reservations` e `verification_visitors` são usadas somente pelas
rotas de verificação; não são registradas como tools dos agentes. A restrição
não depende de o modelo obedecer a uma instrução de privacidade.

### 3. Persistência após reinício

[Runtime.__init__](aurora/runtime.py) conecta sessões e eventos do ADK ao SQLite
em disco. O [Storage](aurora/storage.py) importa os dados iniciais somente quando
a marca `seeded` ainda não existe. Iniciar a API novamente não restaura os dados.

Reservas, cancelamentos, visitantes e pendências de negócio são transacionais.
Cancelamentos preservam a linha inativa. O registro `reservation_codes` não é
apagado nos cancelamentos nem no reset, e `Storage._insert_reservation` registra
cada novo código com unicidade antes de usá-lo.

### 4. Regulamento consultado por assunto

[search_regulations](aurora/regulations.py) lê `dados/regulamento.md` localmente,
seleciona um capítulo por relevância e retorna até dois artigos. Somente esses
resultados entram na resposta da tool e nos eventos. O principal não contém o
texto do regulamento nas instruções; não há tool que devolva o documento inteiro.
Os testes verificam a consulta da piscina aos domingos e a ausência de trechos
de outros capítulos nos eventos dessa consulta.

### 5. Exclusividade no instante da gravação

Em [Storage.__init__](aurora/storage.py), o índice parcial impõe a regra no banco:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS one_active_reservation
ON reservations(area, day) WHERE active = 1;
```

`Storage._transaction` usa `BEGIN IMMEDIATE`. `Storage._insert_reservation`
tenta gravar e trata a violação desse índice como `status: indisponivel`, sem
revelar o morador responsável. Assim, duas aprovações de sessões diferentes para
a mesma área/data resultam em uma única reserva ativa e respostas HTTP 200.
A regra não depende apenas de uma consulta prévia de disponibilidade.

## Como rodar

### Instalação

Requisitos: Git, Python 3.12, [uv](https://docs.astral.sh/uv/) e uma chave do
[Google AI Studio](https://aistudio.google.com/apikey) com acesso a um modelo
Gemini e quota disponível. Python pode ser instalado com `uv python install 3.12`.

```bash
git clone https://github.com/gadrianosl/mba-ia-desafio-criacao-agente.git
cd mba-ia-desafio-criacao-agente
uv sync --locked
cp .env.example .env
```

Preencha a chave no `.env`, que é ignorado pelo Git:

```dotenv
GOOGLE_API_KEY=sua_chave_local
GEMINI_MODEL=gemini-2.5-flash
```

`gemini-2.5-flash` foi usado nos testes manuais. Confirme a disponibilidade e os
limites do seu projeto no AI Studio; o modelo pode ser substituído por outro
Gemini compatível. Variáveis já presentes no processo têm prioridade sobre o
`.env`. Nunca versione a chave. O `.env.example` contém apenas os nomes e uma
sugestão de modelo, sem credenciais.

### Restaurar e iniciar

Para iniciar com os dados originais, com a API e o chat parados:

```bash
uv run python -m aurora.reset
uv run uvicorn aurora.api:app --host 127.0.0.1 --port 8000 --workers 1
```

O reset repõe reservas e visitantes e apaga sessões, eventos e pendências. Os
arquivos de `dados/` não são modificados. O registro histórico de códigos é
preservado para impedir reutilização. Para testar persistência, pare com Ctrl+C
e execute **somente o comando do Uvicorn**, sem reset.

### Contrato e uso

Todas as rotas recebem/devolvem JSON. Sessão inexistente retorna 404;
confirmação inexistente, já respondida ou de outra sessão retorna 409.

| Método | Rota | Entrada ou saída |
| --- | --- | --- |
| POST | `/sessoes` | `{"apartamento":"101"}` → 201, `{"session_id":"..."}` |
| POST | `/sessoes/{session_id}/mensagens` | `{"texto":"..."}` → 200, resposta e pendências |
| POST | `/sessoes/{session_id}/confirmacoes` | `{"id":"...","confirmado":true}` → 200, resposta e pendências |
| GET | `/sessoes/{session_id}/eventos` | Lista ordenada com conteúdo completo dos eventos ADK |
| GET | `/apartamentos/{numero}/reservas` | Lista com `codigo`, `area` e `data` |
| GET | `/apartamentos/{numero}/visitantes` | Lista com `nome` e `data` |

Em outro terminal, crie uma sessão:

```bash
curl -sS -X POST http://127.0.0.1:8000/sessoes \
  -H 'Content-Type: application/json' -d '{"apartamento":"101"}'
```

Substitua o texto abaixo pelo `session_id` retornado:

```bash
SESSION_ID='COLE_O_SESSION_ID'
curl -sS -X POST "http://127.0.0.1:8000/sessoes/$SESSION_ID/mensagens" \
  -H 'Content-Type: application/json' \
  -d '{"texto":"Reserve o salão de festas para 2030-04-20"}'
```

A resposta contém `resposta` e `confirmacoes_pendentes`. Copie o ID da pendência
para aprovar pela rota, não pelo chat:

```bash
CONFIRMATION_ID='COLE_O_ID_DA_CONFIRMACAO'
curl -i -X POST "http://127.0.0.1:8000/sessoes/$SESSION_ID/confirmacoes" \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$CONFIRMATION_ID\",\"confirmado\":true}"
curl -sS http://127.0.0.1:8000/apartamentos/101/reservas
```

Use `false` para negar. Repetir uma confirmação respondida deve retornar 409.
As rotas de verificação são administrativas para este desafio e não passam pelo
modelo. Não há autenticação real ou integração de pagamento neste escopo.

### Validação

```bash
uv run python -m unittest discover -s tests -v
uv run python scripts/verify_acceptance.py --provider local
uv run python scripts/verify_acceptance.py --provider gemini
```

A suíte tem 20 testes. O modo `local` usa uma fixture explícita de modelo; valida
HTTP, Runner, tools e SQLite, mas não avalia a interpretação do Gemini. O modo
`gemini` usa sua chave, consome quota e espera 60 segundos entre operações por
padrão. Pode levar cerca de 20 minutos ou mais. Não há repetição automática de
ações em caso de erro de quota.

O verificador inicia sua própria API em uma porta livre, reinicia esse processo
para testar persistência e usa bancos separados em `.local/acceptance/`.
Se houver um esclarecimento após negar uma reserva, responde uma vez para
renovar o pedido; a aprovação continua obrigatoriamente pela rota. Evidências
ficam em `report.json`, `requests.jsonl` e `server.log`, ignorados pelo Git.

Os testes locais e as verificações manuais de confirmação, consulta, isolamento,
cancelamento e reinício foram executados. A rodada completa com Gemini chegou
ao passo 7 antes de encontrar um esclarecimento não tratado pelo verificador.
O tratamento foi corrigido e testado localmente; a execução completa posterior
com Gemini ainda precisa ser confirmada. Não se declara essa rodada aprovada
sem o relatório correspondente. Instalação, reset, os 20 testes e o roteiro
local de 1 a 15 também passaram em um clone separado. Evidências e limites
estão em [VALIDATION.md](VALIDATION.md); detalhes e diagnóstico estão em
[SETUP.md](SETUP.md).
