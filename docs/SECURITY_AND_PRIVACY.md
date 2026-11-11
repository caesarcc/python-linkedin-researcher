# Requisitos de Segurança e Privacidade (`docs/SECURITY_AND_PRIVACY.md`)

Este documento estabelece as salvaguardas técnicas e operacionais para proteger a conta do LinkedIn, os dados pessoais dos candidatos e a privacidade profissional dos recrutadores pesquisados.

---

## 1. Proteção de Credenciais e Sessão

1. **Zero credenciais no projeto**:
   - O sistema não solicita, não lê e não armazena e-mail de login, senha, códigos MFA ou cookies do LinkedIn em arquivos `.env`, `.json`, `.py` ou `.log`.
2. **Isolamento do perfil de navegador**:
   - O contexto persistente do Playwright utiliza o diretório local `.playwright-profile/` (ignorado pelo `.gitignore`), restrito ao usuário local do sistema operacional.
3. **Autorização do titular**:
   - A sessão autenticada somente deve ser aberta e utilizada com autorização expressa do titular da conta.

---

## 2. Minimização de Dados e Privacidade no Git (LGPD / Boas Práticas)

1. **Proteção Total contra Vazamento no Git (.gitignore)**:
   - Currículos em PDF (`curriculum/*.pdf`);
   - Bancos locais de dados em JSON (`data/*.json`, mantendo apenas templates `data/*.template.json`);
   - Rascunhos de mensagens e relatórios em `output/`;
   - Perfis de sessão do navegador (`.playwright-profile/`).
2. **Dados do candidato**:
   - Os arquivos de currículo e perfil (`data/perfil_candidato.json`) são mantidos exclusivamente em ambiente local.
3. **Dados de recrutadores**:
   - Coletar e armazenar **exclusivamente informações profissionais públicas ou legitimamente visíveis na sessão** e estritamente necessárias para contextualizar o contato profissional:
     - Nome profissional, URL do perfil no LinkedIn, título atual, empresa atual (com flag de confirmação), localização profissional exibida, foco de recrutamento e notas de contexto profissional.
   - **Proibido coletar ou armazenar atributos pessoais sensíveis** (origem racial/étnica, convicção religiosa, opinião política, dados de saúde, vida familiar, telefone pessoal privado, etc.).

---

## 3. Segurança Operacional e Controle Humano

1. **Bloqueio arquitetural de ações externas**:
   - Não existe no sistema funcionalidade para envio automático de mensagens, convites de conexão ou candidaturas.
   - Todas as mensagens geradas em `output/mensagens/` e registradas em `data/contatos.json` nascem com `review_status = "pending_review"` e `sent_by_user = False`.
2. **Proteção contra Injeção de Prompt (Indirect Prompt Injection)**:
   - Textos coletados de perfis, postagens ou descrições de vagas no LinkedIn são tratados como strings literais não confiáveis.
   - O gerador de mensagens e o analisador de vagas utilizam templates controlados e regras determinísticas sobre campos validados, impedindo que instruções maliciosas contidas em uma página web alterem o comportamento do assistente.
3. **Prevenção de Vazamento no Git**:
   - Antes de qualquer commit, verificar com `rtk git status` e `rtk git diff` que nenhum arquivo de `.env`, `.playwright-profile/`, `logs/` ou captura de tela diagnóstica foi incluído no stage.

