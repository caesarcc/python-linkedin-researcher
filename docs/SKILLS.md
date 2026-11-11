# Registro de Skills, Rules e Agents (`docs/SKILLS.md`)

Este documento registra as skills oficiais instaladas, criadas e lidas no ambiente de desenvolvimento, padronizadas na estrutura `.agents/` do **Google Antigravity (Agy)** conforme a **Seção 3 (Competências e skills obrigatórias)** da especificação técnica.

---

## 1. Padronização na Pasta `.agents/` (Padrão Agy)

Seguindo o sistema de descoberta automática de customizações do Antigravity (`agy-customizations`), todas as skills, rules e perfis de agentes do workspace estão centralizados em `.agents/`:

```text
.agents/
├── agents/
│   ├── career-message-writer.md
│   ├── job-matcher.md
│   └── linkedin-researcher.md
├── rules/
│   ├── 01-project-context-and-ethics.md
│   ├── 02-playwright-and-linkedin.md
│   └── 03-python-and-architecture.md
└── skills/
    ├── playwright-cli/          # Skill oficial instalada via @playwright/cli
    │   ├── SKILL.md
    │   └── references/
    │       ├── element-attributes.md
    │       ├── playwright-tests.md
    │       ├── pr-attachments.md
    │       ├── request-mocking.md
    │       ├── running-code.md
    │       ├── session-management.md
    │       ├── storage-state.md
    │       ├── test-generation.md
    │       ├── tracing.md
    │       └── video-recording.md
    └── playwright-python/       # Skill integrada (Playwright Python + playwright-cli)
        └── SKILL.md
    └── developing-with-streamlit/ # Skill oficial para interfaces Web em Streamlit
        ├── SKILL.md
        └── scripts/
            └── discover.py
```

---

## 2. Skills de Playwright Instaladas e Lidas Integralmente

### 2.1. `playwright-cli` (Skill Oficial da Ferramenta Playwright)
- **Localização:** [`.agents/skills/playwright-cli/SKILL.md`](../.agents/skills/playwright-cli/SKILL.md)
- **Origem:** Documentação oficial <https://playwright.dev/agent-cli/skills> — instalada via comando oficial:
  ```powershell
  npx --yes @playwright/cli@latest install --skills=agents
  ```
- **Data de obtenção/instalação:** 2026-11-11
- **Arquivos de referência lidos integralmente:**
  1. `SKILL.md` — Comandos principais (`open`, `goto`, `snapshot`, `find`, `click`, `fill`, `eval`, `generate-locator`, `show --annotate`, `--raw`, `--json`).
  2. `references/session-management.md` — Isolamento de sessões nomeadas (`-s=<name>`), perfis persistentes (`--persistent`, `--profile`), conexão via `attach`/`detach` e limpeza (`close`, `close-all`, `delete-data`).
  3. `references/storage-state.md` — Gerenciamento de cookies, `localStorage`, `sessionStorage`, `state-save`/`state-load` e notas de segurança (nunca commitar estados de autenticação no Git).
  4. `references/running-code.md` — Execução de funções assíncronas customizadas com `run-code`, estratégias de espera (`waitFor`, `waitForFunction`), tratamento de erros e downloads.
  5. `references/tracing.md` — Gravação e inspeção de traces (`tracing-start`, `tracing-stop` em `.playwright-cli/traces/`).
  6. `references/element-attributes.md` — Inspeção de atributos DOM não visíveis no snapshot via `eval`.
  7. `references/request-mocking.md` — Interceptação e mock de rotas (`route`, `route-list`, `unroute`).
  8. `references/playwright-tests.md` — Execução e depuração interativa (`--debug=cli` + `attach`).
  9. `references/test-generation.md` — Fluxo `plan -> generate -> heal`, uso de locators baseados em role (`getByRole`), `generate-locator`, `toMatchAriaSnapshot` e proibição de `networkidle` ou `sleep` como correção.
  10. `references/video-recording.md` e `references/pr-attachments.md` — Gravação de sessões e evidências visuais.

### 2.2. `playwright-python` (Skill Integrada do Projeto)
- **Localização:** [`.agents/skills/playwright-python/SKILL.md`](../.agents/skills/playwright-python/SKILL.md)
- **Origem:** Consolidação da skill oficial `playwright-cli` (<https://playwright.dev/agent-cli/skills>) com a documentação oficial do **Playwright for Python** (<https://playwright.dev/python/> consultada via Context7 MCP `/websites/playwright_dev_python`).
- **Versão / Data:** v2.0.0 (2026-11-11)
- **Principais orientações aplicadas:**
  - Uso combinado do `playwright-cli` (para snapshots leves de acessibilidade e descoberta de locators com `generate-locator`) e do `playwright.async_api` nos módulos Python (`src/linkedin_researcher/browser/`).
  - Uso de `launch_persistent_context` com diretório `.playwright-profile` ignorado pelo Git (junto com `.playwright-cli/`).
  - Locators semânticos resilientes (`get_by_role`, `get_by_label`, `get_by_placeholder`, `get_by_text`), proibição de `networkidle` e de `sleep` para sincronização de DOM.
  - Testes offline em `pytest` com páginas HTML locais e respeito absoluto ao controle humano.

### 2.3. `developing-with-streamlit` (Skill Oficial do Streamlit)
- **Localização:** [`.agents/skills/developing-with-streamlit/SKILL.md`](../.agents/skills/developing-with-streamlit/SKILL.md)
- **Origem:** Skill oficial empacotada no Streamlit (>=1.57), com utilitário de descoberta dinâmica `scripts/discover.py` que localiza as referências e documentação bundled em `site-packages/streamlit`.
- **Finalidade:** Criação, depuração, layouts em abas, estilização de CSS, controle de estado de sessão e performance na interface gráfica interativa do projeto.

---

## 3. Outras Skills do Ambiente Consultadas

- **`agy-customizations`** (`C:\Users\caesar.cesar\.gemini\antigravity\builtin\skills\agy-customizations\SKILL.md`) — Guia oficial do sistema de customização do Antigravity utilizado para padronizar `.agents/skills/`, `.agents/rules/` e `.agents/agents/`.
- **`context7-mcp`** (`C:\Users\caesar.cesar\.gemini\config\plugins\context7\skills\context7-mcp\SKILL.md`) — Consulta à documentação atualizada do Playwright Python.
- **`managing-python-dependencies`** (`C:\Users\caesar.cesar\.gemini\config\skills\managing-python-dependencies\SKILL.md`) — Gerenciamento estrito de `.venv`, `pyproject.toml` e `requirements.txt`.
- **`rtk-token-optimizer`** (`C:\Users\caesar.cesar\.gemini\config\skills\rtk-token-optimizer\SKILL.md`) — Otimização de comandos CLI com `rtk`.
