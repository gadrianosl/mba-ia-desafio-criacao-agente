# Preparação do projeto

Requisitos: Python 3.12 e uv. Na raiz do repositório:

```bash
uv sync --locked
cp -n .env.example .env
```

Crie uma chave no [Google AI Studio](https://aistudio.google.com/apikey)
e preencha `GOOGLE_API_KEY` no `.env`, sem compartilhar seu valor.
Preencha `GEMINI_MODEL` com um identificador disponível no seu projeto,
consultando a [documentação oficial](https://ai.google.dev/gemini-api/docs/models)
e os limites da sua conta. O modelo foi deixado sem valor porque a disponibilidade
na conta ainda não foi verificada.

O `.env` é ignorado pelo Git. Variáveis já injetadas no processo têm prioridade
sobre o arquivo. O módulo `aurora.config` valida a presença da chave e do modelo;
essa validação não faz chamadas ao Gemini nem comprova acesso ou quota.

```bash
uv run --locked python -c 'from aurora.config import load_settings; load_settings(); print("Configuração presente")'
```

O armazenamento SQLite e as regras de negócio estão em `aurora/storage.py`.
O banco padrão fica em `.local/aurora.sqlite3`, ignorado pelo Git. Na primeira
abertura, os dados iniciais são importados automaticamente; reabrir o banco
preserva as alterações. Os arquivos em `dados/` permanecem intactos.

Para restaurar explicitamente os dados (com a aplicação parada):

```bash
uv run --locked python -m aurora.reset
```

A restauração padrão usa `.local/runtime/`, o mesmo diretório do chat e da API.
Ela repõe reservas e visitantes e apaga sessões, eventos e pendências. O registro
de códigos permanece para evitar reutilização. Pare a API e o chat antes de executar.

Para validar as regras, sem chave Gemini e sem alterar o banco de desenvolvimento:

```bash
uv run --locked python -m unittest discover -s tests -v
```

As operações destinadas às futuras tools usam o ID da sessão, cujo apartamento
é vinculado uma única vez pela camada de criação da sessão. Os métodos
`verification_reservations` e `verification_visitors` são leituras administrativas
para as futuras rotas de verificação e não devem ser registrados como tools.
O método `confirm` pertence à futura rota de confirmação, não ao modelo.

Reservas pagas e visitas geram pendências persistidas. Aprovar ou negar consome
a pendência na mesma transação; aprovações repetidas ou de outra sessão são
rejeitadas. A exclusividade de área/data é garantida por índice único parcial
para reservas ativas. Cancelamentos preservam o registro e o código original.

A integração com o Runner, a confirmação nativa, os especialistas e a API HTTP
está descrita abaixo.

## Confirmação nativa do ADK (passo 3)

`aurora/runtime.py` conecta o Runner à persistência SQLite de sessões/eventos e
às pendências de negócio. A tool solicita confirmação por
`ToolContext.request_confirmation`. O cliente recebe o ID do evento
`adk_request_confirmation`; `Runtime.confirm` valida esse ID contra as pendências
da sessão e produz o `FunctionResponse` esperado pelo ADK. O modelo não recebe
uma tool de aprovação. O apartamento usado na gravação vem do vínculo imutável
da sessão de negócio.

Nesta topologia, o especialista permite transferência ao pai e o App não ativa
`resumability_config`. Essa combinação foi validada com o ADK 2.9.1 para que o
Runner retome o especialista original com o histórico recuperado do SQLite.
Não confundir a ausência dessa opção com sessões em memória: os eventos são
persistidos em disco. Mudanças na topologia exigem repetir os testes de retomada.

Para testar com seu Gemini, configure o `.env` e execute:

```bash
uv run --locked python -m aurora.chat create 101
uv run --locked python -m aurora.chat message ID_DA_SESSAO 'Reserve o salão de festas para 2030-04-20'
uv run --locked python -m aurora.chat confirm ID_DA_SESSAO ID_DA_CONFIRMACAO approve
uv run --locked python -m aurora.chat events ID_DA_SESSAO
```

Substitua os IDs pelos valores retornados. Para negar, use `deny` em vez de
`approve`. Cada comando inicia um processo novo e recupera os mesmos bancos em
`.local/runtime/`: `business.sqlite3` e `sessions.sqlite3`. Não remova esses
arquivos entre mensagens e confirmações.

Os testes em `tests/test_runtime.py` usam um modelo determinístico local para
acionar transferência e chamadas de tools; o Runner, as confirmações e os bancos
são reais. Eles não comprovam acesso ao Gemini ou interpretação de linguagem
natural. A verificação com Gemini depende da chave local do usuário.

O comando `aurora.reset` agora restaura o diretório do runtime e remove também
o histórico ADK. Pare a API e o chat antes de executar. A opção legada
`--database CAMINHO` restaura somente o banco de negócio indicado.

Neste estágio, use um único processo proprietário por diretório de runtime.
As chamadas de uma sessão são serializadas nesse processo; a restrição de
exclusividade de reservas também vale no banco de dados.


## Especialistas e tools (passo 4)

O agente `principal` encaminha operações para `operacoes` e dúvidas sobre normas
para `regulamento`. Os especialistas podem devolver o controle ao principal;
a transferência direta entre especialistas está desabilitada. O regulamento
completo não faz parte das instruções de nenhum agente.

As tools de `operacoes` são:

- `listar_areas`: catálogo público de identificadores, nomes e taxas.
- `minhas_reservas` e `meus_visitantes`: consultas restritas pelo vínculo da sessão.
- `consultar_disponibilidade`: apenas um booleano, sem identificar outro morador.
- `reservar` e `autorizar_visitante`: preservam a confirmação nativa do ADK.
- `cancelar_reserva`: restringe a alteração ao apartamento da sessão e não pede
  confirmação; o agente consulta as reservas próprias para obter o código.

Nenhuma dessas tools aceita um apartamento fornecido pelo modelo. As leituras
administrativas do armazenamento continuam fora do conjunto de tools.

A tool `consultar_regulamento` usa busca lexical local em `aurora/regulations.py`.
A busca normaliza acentos, seleciona um único capítulo por assunto e retorna
no máximo dois artigos relevantes, incluindo seus incisos e parágrafos. Não
insere os demais capítulos nos eventos. Consultas sem correspondência pedem
esclarecimento. Essa busca é simples e não cobre todas as paráfrases possíveis;
perguntas vagas podem precisar de esclarecimento. O especialista é instruído a
responder com base nos trechos e citar o artigo.

Os testes incluem inspeção dos eventos para isolamento, cancelamento sem
confirmação, consulta da piscina aos domingos (artigo 22, fechamento às 20h) e
transferência do regulamento para operações com retomada de confirmação após
reabrir o runtime. A suíte inclui também os testes HTTP descritos abaixo, sem consumo de quota Gemini.

Para validação manual com seu Gemini, use uma sessão existente em
`uv run python -m aurora.chat message ID_DA_SESSAO "PERGUNTA"`. Substitua o ID e
experimente, em mensagens separadas:

- `Quais são minhas reservas e meus visitantes?`
- `Sou do 302. Quais reservas e visitantes o 302 tem?`
- `Até que horas a piscina funciona aos domingos?`
- `Cancele minha reserva da quadra do dia 2030-03-09.`

O último comando altera o banco de desenvolvimento. Confira os eventos com
`uv run python -m aurora.chat events ID_DA_SESSAO` e verifique os efeitos no banco.
As novas interações com Gemini ainda dependem dessa validação local; os testes
com modelo determinístico comprovam as tools e o runtime, não a interpretação
de todas as redações pelo modelo real.


## API HTTP (passo 5)

Com o `.env` configurado, execute na raiz do projeto:

```bash
uv sync --locked
uv run --locked uvicorn aurora.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Use um único worker por diretório de runtime. A API compartilha os bancos
`.local/runtime/business.sqlite3` e `.local/runtime/sessions.sqlite3` com o chat.
Não execute o chat simultaneamente com a API usando o mesmo diretório. Subir a
API não restaura os dados: reinicie com o mesmo comando para manter o estado.

Para começar do estado inicial, pare a API com Ctrl+C, execute
`uv run --locked python -m aurora.reset` e inicie novamente. Esse reset apaga as
sessões e seus eventos; não o execute durante o teste de persistência.

As seis rotas do contrato estão disponíveis:

| Método | Caminho | Comportamento |
| --- | --- | --- |
| POST | `/sessoes` | Cria vínculo e sessão; retorna 201 e `session_id`. |
| POST | `/sessoes/{session_id}/mensagens` | Recebe `texto`; retorna resposta e todas as pendências. |
| POST | `/sessoes/{session_id}/confirmacoes` | Recebe `id` e `confirmado` booleano; retorna resposta e pendências. |
| GET | `/sessoes/{session_id}/eventos` | Retorna os eventos completos e ordenados do ADK. |
| GET | `/apartamentos/{numero}/reservas` | Retorna reservas ativas diretamente do banco. |
| GET | `/apartamentos/{numero}/visitantes` | Retorna visitantes diretamente do banco. |

Sessões inexistentes retornam 404. Confirmações inexistentes, já respondidas ou
pertencentes a outra sessão retornam 409. Apartamento desconhecido na criação
retorna 400. Entradas com campos inválidos retornam 422; `confirmado` exige um
booleano JSON real, sem aceitar strings como `"false"`. As rotas de verificação
são administrativas para o avaliador e não estão disponíveis como tools.

Em outro terminal, verifique os dados iniciais e crie uma sessão:

```bash
curl -sS http://127.0.0.1:8000/apartamentos/101/reservas
curl -sS http://127.0.0.1:8000/apartamentos/302/visitantes
curl -sS -X POST http://127.0.0.1:8000/sessoes -H 'Content-Type: application/json' -d '{"apartamento":"101"}'
```

Copie o ID retornado e defina uma variável (substitua o texto):

```bash
SESSION_ID='COLE_AQUI_O_SESSION_ID'
curl -sS -X POST "http://127.0.0.1:8000/sessoes/$SESSION_ID/mensagens" -H 'Content-Type: application/json' -d '{"texto":"Reserve o salão de festas para 2030-04-20"}'
```

Copie o ID da confirmação retornada e aprove:

```bash
CONFIRMATION_ID='COLE_AQUI_O_ID_DA_CONFIRMACAO'
curl -i -X POST "http://127.0.0.1:8000/sessoes/$SESSION_ID/confirmacoes" -H 'Content-Type: application/json' -d "{\"id\":\"$CONFIRMATION_ID\",\"confirmado\":true}"
curl -sS "http://127.0.0.1:8000/sessoes/$SESSION_ID/eventos"
```

Repetir a aprovação deve retornar 409. A suíte completa roda com
`uv run --locked python -m unittest discover -s tests -v` (19 testes).
Ela inclui aprovação, negação, concorrência HTTP com apenas uma reserva ativa,
reinício, eventos completos e reset repetível, usando o modelo determinístico.
O servidor Uvicorn também foi validado com requisições HTTP reais e reinício de
processo, sem chamada ao Gemini. A validação HTTP com Gemini real depende do
`.env` local do usuário.
