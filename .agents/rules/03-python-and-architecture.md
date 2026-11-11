# Regra 03 — Engenharia Python, Arquitetura e Testes

## 1. Ambiente e Dependências

- Utilizar exclusivamente o ambiente virtual local `.venv` (Python 3.11+): `.venv\Scripts\python.exe`, `.venv\Scripts\pip.exe`, `.venv\Scripts\pytest.exe`.
- Nunca executar `pip install` globalmente. Manter `pyproject.toml` e `requirements.txt` sincronizados.
- Prefira prefixar comandos CLI suportados com `rtk` (`rtk pytest`, `rtk git status`, `rtk ruff check`).

## 2. Arquitetura Modular (`src/linkedin_researcher/`)

- Manter separação estrita entre:
  - `models.py` (entidades Pydantic v2 validadas);
  - `storage.py` (persistência atômica em `data/*.json` com deduplicação);
  - `browser/` (apenas Playwright e extração de páginas);
  - `research/` (coleta e normalização de recrutadores, empresas e vagas);
  - `analysis/` (perfil curricular configurável do candidato, matching explicável e ranking);
  - `messaging/` (geração de rascunhos em primeira pessoa, sem envio);
  - `cli.py` (interface de linha de comando `linkedin-researcher`).

## 3. Testes Automatizados

- Executar `rtk pytest` após cada etapa implementada.
- Nenhum teste automatizado pode depender de conexão real ao LinkedIn ou enviar mensagens/convites/candidaturas. Utilizar fixtures e páginas HTML locais.
