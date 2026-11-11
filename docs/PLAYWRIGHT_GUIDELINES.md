# Diretrizes de Automação com Playwright (`docs/PLAYWRIGHT_GUIDELINES.md`)

Estas diretrizes regem todo o código dentro de `src/linkedin_researcher/browser/` e `src/linkedin_researcher/research/`.

---

## 1. Sessão Autenticada e Controle Humano

1. **Inicialização interativa pelo usuário**: A autenticação no LinkedIn deve ser feita manualmente pelo titular da conta através do comando `linkedin-researcher browser login`.
2. **Contexto persistente isolado**:
   - Usar `playwright.chromium.launch_persistent_context(user_data_dir=...)` apontando para `.playwright-profile/` (configurável via `LINKEDIN_USER_DATA_DIR`).
   - Nunca reutilizar o diretório de perfil padrão do Chrome/Edge pessoal da máquina sem autorização explícita.
   - O diretório `.playwright-profile/` deve estar listado no `.gitignore`.
3. **Sem armazenamento de credenciais**:
   - Nunca solicitar senha via CLI ou variáveis de ambiente.
   - Nunca exportar ou commitar cookies, tokens (`li_at`, etc.) ou `storage_state.json` no repositório.
4. **Pausa diante de desafios de segurança**:
   - Se a página redirecionar para `/login`, `/checkpoint/`, `/challenge/` ou exibir CAPTCHA/MFA, interromper imediatamente a navegação automatizada, registrar aviso no log e solicitar intervenção manual da usuária.

---

## 2. Seletores Resilientes e Auto-Wait

1. **Ordem de preferência de seletores**:
   - `page.get_by_role(...)` (ex.: `heading`, `button`, `link`, `main`, `navigation`, `listitem`)
   - `page.get_by_label(...)`
   - `page.get_by_placeholder(...)`
   - `page.get_by_text(...)`
   - Seletores CSS semânticos combinados com `locator.filter(has_text=...)`
2. **Proibições**:
   - Não utilizar XPath absoluto.
   - Não depender de classes CSS dinâmicas/geradas por build (hashes) sem fallback semântico.
3. **Sincronização**:
   - Utilizar o auto-wait nativo do Playwright e `await locator.wait_for(state="visible", timeout=...)`.
   - Não usar `time.sleep()`.
   - Usar `await asyncio.sleep(delay)` apenas entre navegações de páginas para respeitar limites de frequência.

---

## 3. Limites de Uso e Respeito à Plataforma

- **Apenas consultas pontuais**: Cada execução de pesquisa na CLI opera sobre um recrutador, empresa ou busca específica solicitada pela pessoa usuária.
- **Pausas entre navegações**: Respeitar o intervalo configurável (`LINKEDIN_MIN_ACTION_DELAY_SEC` a `LINKEDIN_MAX_ACTION_DELAY_SEC`, padrão 3 a 7 segundos).
- **Proibição de evasão**: Não usar proxies, rotação de contas, adulteração de cabeçalhos/fingerprints ou bibliotecas de stealth.
- **Proibição de ações externas**: O código do Playwright **não pode** conter chamadas `.click()` ou `.press("Enter")` em botões de envio de mensagem, convite de conexão ou candidatura a vagas.

---

## 4. Rastreabilidade, Layout SDUI e Confirmação de Dados `Pendente`

Toda extração realizada por `linkedin_pages.py` e processada em `research/` deve:
- Registrar a `source_url` exata e o timestamp `checked_at` (ISO-8601).
- Preservar o texto relevante observado na página.
- Distinguir claramente **dado observado** (ex.: empresa listada como atual no bloco "Experiência" ou no Top Card) de **dado não confirmado** (`company_verified = False`, `"a confirmar"` / `"Pendente"`).
- Suportar tanto o layout clássico do LinkedIn (`<h1>`, `ul > li.artdeco-list__item`) quanto o layout **SDUI moderno**, em que:
  - O nome principal do perfil no Top Card pode ser renderizado em `<h2>` (além de `<h1>`);
  - A empresa atual aparece no cabeçalho logo após `"Dados de contato"` (ex.: `"Unidão Transportes e mais 2 empresas"`), no card `"Contratando: ..."` ou na subpágina `/in/<slug>/details/experience/`;
  - Quando a seção `Experiência` na página principal do perfil permanece como placeholder vazio até rolagem profunda, `extract_recruiter_profile_page` consulta automaticamente `/in/<slug>/details/experience/` para extrair os cargos agrupados/individuais com datas `"o momento"` / `"atual"`.
- Permitir confirmação manual assistida via CLI (`recruiters set-url` e `recruiters update --id <id> --company "<Empresa>" --verified`) sempre que um perfil não declarar empresa publicamente ou houver homônimos.
- Tratar ausências de elementos na página com falhas controladas (retornando campos opcionais vazios e nota de diagnóstico, sem abortar abruptamente o programa).

---

## 5. Testes de Automação

- Nenhum teste em `tests/` deve realizar requisições de rede para `linkedin.com`.
- Os testes de extração e tratamento de erros de navegação devem usar páginas HTML estáticas locais (`page.set_content(...)` ou arquivos HTML locais em `tests/`) ou mocks controlados.

