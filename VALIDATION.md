# Validação da entrega

Revisão realizada em 27/10/2026.

| Verificação | Resultado |
| --- | --- |
| `uv sync --locked` em clone separado, com `.venv` nova | Passou |
| Comando documentado de restauração em banco novo | Passou |
| Suíte automatizada no clone separado | 20 testes passaram |
| Verificador de aceitação com fixture local no clone separado | Passos 1 a 15 passaram |
| Reinício de Uvicorn, recuperação integral dos eventos e continuação da sessão | Passou no roteiro HTTP |
| Duas aprovações simultâneas de reserva | HTTP 200 nas duas; exatamente uma reserva ativa |
| Dados comparados com o repositório oficial | Idênticos |
| Busca de padrões conhecidos de chave Google no histórico Git | Nenhum encontrado |
| `.env` fora do Git e exemplo com chave vazia | Conferido |
| README com Arquitetura, Garantias, Como rodar e referências existentes | Conferido |
| Rodada completa com Gemini real após a última correção | Pendente de execução no computador do usuário |

A comparação oficial foi feita por fetch HTTPS de
`https://github.com/devfullcycle/mba-ia-desafio-criacao-agente.git`, branch `main`,
no commit `be87e1d09ac5b49b26336ef8f7328adafd136971`, seguida de comparação de
`dados/`. Nenhuma diferença foi encontrada.

O clone separado foi criado a partir do checkout local commitado, com histórico
Git completo e sem reutilizar a `.venv`, o `.env` ou os bancos do checkout
principal. Os resultados acima não afirmam que foi testada a disponibilidade
de todos os artefatos de instalação fora do cache ou em todos os sistemas
operacionais.

No computador do usuário, as validações manuais com Gemini real confirmaram
reserva paga, aprovação única e conflito na repetição, consultas de reservas e
visitantes, recusa de acesso a outro apartamento, cancelamento próprio,
regulamento da piscina e persistência pela API após reinício. O roteiro real
mais recente passou pelos passos 1 a 7 e parou no passo 8 porque o agente pediu
esclarecimento depois de uma confirmação negada. O código e o verificador foram
ajustados: novo pedido deve criar outro ID; o roteiro pode responder uma vez ao
esclarecimento, mas a aprovação permanece exclusivamente pela rota. A correção
foi validada com fixture local e teste de regressão; isso não comprova o resultado
da nova rodada com Gemini real.

Para concluir essa evidência, com `.env` configurado:

```bash
uv run python scripts/verify_acceptance.py --provider gemini
```

Preserve o `report.json` e os logs da execução em `.local/acceptance/`.
O modo local não substitui esse teste: sua fixture decide as chamadas previstas
para os pedidos do roteiro, sem avaliar a compreensão do modelo real.
