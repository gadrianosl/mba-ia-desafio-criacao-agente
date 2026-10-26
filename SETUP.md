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

A restauração apaga vínculos de sessões e confirmações desta camada e repõe
reservas e visitantes. O registro de códigos permanece para evitar reutilização.
O histórico de sessões do ADK ainda não foi integrado e não é gerenciado por
esse comando neste estágio.

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

A API e os agentes ainda não estão implementados. A integração dessas pendências
com confirmação de tools, eventos e retomada do Runner do ADK será feita e
validada separadamente, incluindo reinício. A consulta seletiva ao regulamento
será implementada com o especialista correspondente.

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

O comando `aurora.reset` do passo 2 restaura apenas o banco de negócio escolhido;
ele não limpa o histórico ADK. Não o execute sobre o banco do runtime enquanto
houver sessões em uso. O reset integrado, as rotas HTTP e o segundo especialista
(regulamento) ainda serão implementados.

Neste estágio, use um único processo proprietário por diretório de runtime.
As chamadas de uma sessão são serializadas nesse processo; a restrição de
exclusividade de reservas também vale no banco de dados.
