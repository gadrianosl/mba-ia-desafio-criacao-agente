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
