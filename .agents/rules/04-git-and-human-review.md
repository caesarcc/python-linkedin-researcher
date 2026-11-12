# Regra 04 — Controle Humano de Git (Commits e Push)

## 1. Proibição de Commit e Push Automáticos

- **PROIBIDO executar `git commit` ou `git push` automaticamente**: O agente **NUNCA** deve realizar commits ou push para o repositório remoto sem a revisão prévia e autorização explícita do usuário.
- **Fluxo de Entrega Obrigatório**:
  1. Ao concluir qualquer alteração no código, testes ou documentação, o agente deve deixar os arquivos editados na árvore de trabalho (*working tree*), sem executar `git commit` ou `git push`.
  2. O agente deve executar os testes e linters (`pytest`, `ruff check`) e apresentar o resumo dos arquivos modificados para conferência.
  3. O **usuário** fará a revisão das alterações, redigirá a mensagem de commit e executará o commit e o push no GitHub (salvo solicitação explícita em contrário).

