---
name: playwright-python
description: >-
  Use this skill when developing, inspecting, debugging, or testing browser automation
  in Python with Playwright (playwright.async_api) alongside the official Playwright Agent CLI
  (playwright-cli) skill installed in .agents/skills/playwright-cli.
license: MIT
metadata:
  version: 2.0.0
  obtained_at: "2026-11-11"
  sources:
    - "Playwright Agent CLI Official Skills (https://playwright.dev/agent-cli/skills — installed at .agents/skills/playwright-cli)"
    - "Playwright for Python Official Documentation (https://playwright.dev/python/ via Context7 MCP)"
---

# Playwright Python & Agent CLI (`playwright-cli`) — Guia Integrado

Esta skill une as capacidades oficiais do **Playwright Agent CLI** ([`.agents/skills/playwright-cli/SKILL.md`](../playwright-cli/SKILL.md) e suas 10 referências em [`.agents/skills/playwright-cli/references/`](../playwright-cli/references/)) com a implementação em **Python (`playwright.async_api`)** do projeto **LinkedIn Researcher & Career Assistant**.

---

## 1. Quando Usar `playwright-cli` vs. `playwright.async_api` (Python)

1. **`playwright-cli` (Exploração interativa, inspeção de árvore de acessibilidade, descoberta de seletores e diagnóstico pelo Agente):**
   - Mantém sessão ativa e consome poucos tokens usando snapshots YAML da árvore de acessibilidade (`playwright-cli snapshot`, `playwright-cli find`) em vez de despejar o DOM bruto.
   - Gera automaticamente locators semânticos resilientes (`playwright-cli --raw generate-locator <ref>`).
   - Permite gerenciar sessões nomeadas (`-s=linkedin-researcher`) e perfis persistentes (`--profile=.playwright-profile`).
   - Referência completa: [`.agents/skills/playwright-cli/SKILL.md`](../playwright-cli/SKILL.md).

2. **`playwright.async_api` (Módulos da aplicação Python em `src/linkedin_researcher/browser/` e testes `pytest`):**
   - Implementa a automação determinística executada pela CLI do projeto (`linkedin-researcher` ou `python -m linkedin_researcher.cli ...`).
   - Consome os seletores semânticos descobertos/validados (`get_by_role`, `get_by_label`, `get_by_placeholder`, `get_by_text`).

---

## 2. Fluxo Oficial de Descoberta de Seletores e Inspeção com `playwright-cli`

Sempre que precisar inspecionar a estrutura de uma página ou descobrir o melhor locator para usar em `src/linkedin_researcher/browser/linkedin_pages.py`:

```powershell
# 1. Abrir sessão nomeada com perfil persistente dedicado (em modo visível para login manual)
npx playwright-cli -s=linkedin-researcher open https://www.linkedin.com --persistent --profile=.playwright-profile --headed

# 2. Capturar snapshot da árvore de acessibilidade (ou limitar profundidade para economia de tokens)
npx playwright-cli -s=linkedin-researcher snapshot --depth=4

# 3. Buscar elementos específicos no snapshot com contexto (sem carregar a página inteira)
npx playwright-cli -s=linkedin-researcher find "Experiência"
npx playwright-cli -s=linkedin-researcher find --regex "/(Assistente|Analista) Financeiro/i"

# 4. Gerar locator semântico resiliente a partir da referência (ex.: e15)
npx playwright-cli -s=linkedin-researcher --raw generate-locator e15
# Saída equivalente em Python: page.get_by_role("heading", name="Experiência")

# 5. Inspecionar atributos não visíveis no snapshot quando estritamente necessário
npx playwright-cli -s=linkedin-researcher --raw eval "el => el.getAttribute('aria-label')" e15

# 6. Encerrar a sessão de forma limpa
npx playwright-cli -s=linkedin-researcher close
```

> **Atenção para URLs com `&` no Windows PowerShell:** conforme documentado na skill oficial `playwright-cli`, utilize `--%` ou escape adequado para evitar truncamento de parâmetros de query.

### Referências oficiais detalhadas do `playwright-cli`
- Gerenciamento de sessões (`-s`, `--persistent`, `--profile`, `attach`/`detach`): [session-management.md](../playwright-cli/references/session-management.md)
- Estado de armazenamento e segurança (`state-save`, `state-load`, cookies): [storage-state.md](../playwright-cli/references/storage-state.md)
- Inspeção de atributos DOM (`eval`): [element-attributes.md](../playwright-cli/references/element-attributes.md)
- Execução de scripts customizados (`run-code`): [running-code.md](../playwright-cli/references/running-code.md)
- Tracing e diagnóstico (`.playwright-cli/traces/`): [tracing.md](../playwright-cli/references/tracing.md)
- Mocking de requisições (`route`, `unroute`): [request-mocking.md](../playwright-cli/references/request-mocking.md)
- Geração e manutenção de testes (`plan -> generate -> heal`): [test-generation.md](../playwright-cli/references/test-generation.md)

---

## 3. Inicialização e Encerramento do Browser em Python (`playwright.async_api`)

```python
from pathlib import Path
from playwright.async_api import async_playwright, BrowserContext


async def open_persistent_context(user_data_dir: Path, headless: bool = False) -> None:
    user_data_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        context: BrowserContext = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=headless,
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
        )
        try:
            context.set_default_timeout(30_000)
            context.set_default_navigation_timeout(45_000)
            page = context.pages[0] if context.pages else await context.new_page()
            # Navegação e extração controlada...
        finally:
            await context.close()
```

---

## 4. Autenticação e Persistência de Sessão

- **Login 100% manual e interativo:** O comando `linkedin-researcher browser login` (ou `python -m linkedin_researcher.cli browser login`) abre o navegador em `headless=False` usando `.playwright-profile/`.
- **Proibição de armazenamento de credenciais:** Nunca salvar senhas, cookies ou arquivos `auth.json` / `storage-state.json` no Git. Tanto `.playwright-profile/` quanto `.playwright-cli/` estão no `.gitignore`.
- **Pausa imediata em desafios:** Se a URL redirecionar para `/login`, `/checkpoint/` ou `/challenge/`, pausar a automação e solicitar ação humana.

---

## 5. Seletores Resilientes, Locators e Auto-Wait

- Converter os locators gerados por `playwright-cli generate-locator` para a sintaxe Python snake_case:
  - `getByRole('button', { name: ' Pesquisar ' })` $\rightarrow$ `page.get_by_role("button", name="Pesquisar")`
  - `getByLabel('...')` $\rightarrow$ `page.get_by_label("...")`
  - `getByPlaceholder('...')` $\rightarrow$ `page.get_by_placeholder("...")`
  - `getByText('...')` $\rightarrow$ `page.get_by_text("...")`
- **Nunca usar `networkidle`** para aguardar carregamento em páginas SPA pesadas (recomendação expressa na referência oficial `test-generation.md` Seção 3.3: *"Never skip hooks or add sleeps as a fix. Never use `networkidle`"*). Prefira `wait_until="domcontentloaded"` seguido de `await locator.wait_for(state="visible")`.

---

## 6. Tratamento de Navegação, Timeouts, Logs e Testes

- Capturar `from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError`.
- Para diagnóstico profundo, usar `context.tracing.start(screenshots=True, snapshots=True)` em Python ou `playwright-cli tracing-start` / `tracing-stop` via CLI, salvando artefatos apenas em diretórios ignorados pelo Git (`logs/` ou `.playwright-cli/`).
- Testes em `tests/` com `pytest` e `pytest-asyncio` utilizam HTML estático local (`page.set_content`) ou mocks, sem jamais acessar o LinkedIn real ou enviar mensagens/convites/candidaturas.

