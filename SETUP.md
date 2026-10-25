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

Este estágio prepara as dependências e a configuração. A API, os agentes,
o banco de dados e o comando de restauração ainda serão implementados.
Os dados em `dados/` devem permanecer intactos.
