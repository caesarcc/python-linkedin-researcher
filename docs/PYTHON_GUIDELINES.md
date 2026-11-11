# Diretrizes de Desenvolvimento Python (`docs/PYTHON_GUIDELINES.md`)

## 1. Versão e Ambiente

- **Versão mínima:** Python 3.11+ (desenvolvido e validado com CPython 3.11+).
- **Ambiente virtual dedicado:** `.venv/` na raiz do repositório.
- **Gerenciamento de pacotes:**
  - Definição declarativa de dependências e metadados em `pyproject.toml`.
  - Lock de versões instaladas em `requirements.txt` (`pip freeze > requirements.txt`).
  - Proibido executar `pip install` fora do `.venv`.

---

## 2. Estilo de Código e Tipagem

- **Type Hints obrigatórios**: Todas as funções, métodos públicos e atributos de modelos devem possuir anotações de tipo explícitas (`from __future__ import annotations`, `str | None`, `list[str]`, etc.).
- **Caminhos de sistema de arquivos**: Utilizar exclusivamente `pathlib.Path` em vez de concatenação de strings ou `os.path`.
- **Modelagem de dados**: Utilizar `pydantic.BaseModel` (Pydantic v2) para validação de entrada/saída, serialização JSON e invariantes de domínio.
- **Assincronismo**:
  - A camada `browser/` e métodos de pesquisa que interagem com o Playwright devem usar `async def` / `await` (`playwright.async_api`).
  - A lógica pura de domínio (`models.py`, `storage.py`, `analysis/`, `messaging/`) deve permanecer síncrona, determinística e facilmente testável sem navegador.
- **Formatação e Linting**: Seguir PEP 8 com limite de linha de 100 caracteres, verificado via `ruff`.

---

## 3. Tratamento de Erros e Logging

- **Logging estruturado**:
  - Utilizar o módulo `logging` configurado em `src/linkedin_researcher/logging_config.py`.
  - Nunca usar `print()` para diagnóstico interno em módulos de biblioteca (reservar saída de terminal formatada para `cli.py`).
  - Nunca registrar senhas, cookies, tokens de sessão ou dados pessoais sensíveis nos logs.
- **Exceções específicas**:
  - Capturar exceções específicas (`PlaywrightTimeoutError`, `ValidationError`, ` json.JSONDecodeError`, `OSError`).
  - Produzir mensagens de erro claras e acionáveis para a pessoa usuária na CLI.

---

## 4. Testes Automatizados (`pytest`)

- Todos os testes ficam em `tests/` e são executados via `rtk pytest` (ou `.venv\Scripts\pytest`).
- Cobertura obrigatória para o MVP:
  1. Validação dos modelos (`test_models.py`);
  2. Leitura, gravação e deduplicação no armazenamento (`test_storage.py`);
  3. Classificação explicável de aderência de vagas (`test_job_matching.py`);
  4. Geração e personalização de mensagens sem envio (`test_message_generator.py`);
  5. Tratamento de erros de navegação e extração em HTML local (`conftest.py` / testes de página local).

