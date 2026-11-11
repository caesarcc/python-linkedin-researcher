# LinkedIn Researcher & Career Assistant

Ferramenta local, ética e modular em Python com automação assistida por Playwright para apoiar a recolocação profissional e pesquisa de mercado de candidatos no LinkedIn. O sistema identifica e enriquece perfis de recrutadores e empresas, monitora oportunidades, analisa a aderência de vagas ao currículo comprovado e prepara rascunhos de mensagens para **revisão e controle humano obrigatório**.

---

## 🔒 Princípios Éticos e de Segurança Invioláveis (Git Safe)

1. **Zero Dados Pessoais no Repositório:** Currículos em PDF (`curriculum/*.pdf`), arquivos markdown de contexto (`data/*.md`), bancos de dados locais em JSON (`data/*.json`) e relatórios de oportunidades ou mensagens (`output/**/*`) são estritamente ignorados pelo Git via `.gitignore`.
2. **Zero Armazenamento de Credenciais:** Senhas, cookies de sessão e tokens de autenticação **nunca** são gravados em código, arquivos rastreados ou commits.
3. **100% de Controle Humano:** O sistema **nunca** envia mensagens, solicitações de conexão ou candidaturas automaticamente. Todas as ações de abordagem passam por revisão manual humana obrigatória.
4. **Navegação Respeitosa e Assistida:** Ações no navegador possuem pausas aleatórias (delays de 3 a 7 segundos) e operam com perfil persistente local (`.playwright-profile/`). Qualquer desafio de autenticação (MFA, CAPTCHA, checkpoint) pausa imediatamente a automação para intervenção humana direta.
5. **Defesa contra Injeção de Instruções (Prompt Injection):** Todo conteúdo textual extraído do LinkedIn (perfis, vagas, publicações) é tratado exclusivamente como dado bruto passivo e nunca como instrução executável.

---

## ⚙️ Configuração Rápida de um Novo Candidato

A configuração de um novo perfil é extremamente simples e não exige alteração em nenhum arquivo de código Python:

```text
1. curriculum/<Nome_do_Candidato>.pdf   <- Currículo em PDF (exclusivo, .docx é rejeitado)
2. data/<Nome_do_Candidato>.md         <- Informações adicionais e recrutadores para pesquisa
3. linkedin-researcher profile build     <- Comando CLI que gera os arquivos JSON automaticamente
```

### Passo a Passo

1. **Adicionar o Currículo em PDF:**
   - Coloque o arquivo PDF do currículo dentro da pasta `curriculum/` (exemplo: `curriculum/Joao_Silva_CV.pdf`).
   - *Nota de segurança:* Arquivos Word (`.docx` ou `.doc`) são estritamente rejeitados pelo sistema.

2. **Criar o Arquivo de Informações Adicionais (com o mesmo nome base):**
   - Crie o arquivo markdown em `data/<Nome_do_Candidato>.md` (exemplo: `data/Joao_Silva_CV.md`).
   - Você pode usar o modelo limpo [`data/informacoes_adicionais.template.md`](data/informacoes_adicionais.template.md) como ponto de partida.
   - Esse arquivo complementa o currículo com:
     - **Priorização de áreas afins:** Vagas compatíveis com as competências reais mesmo que títulos específicos não estejam literalmente no currículo (ex: Faturamento, Contas a Pagar/Receber, Back Office, Cobrança).
     - **Restrições e cargos excluídos:** Posições que não devem ser priorizadas (ex: cargos de gerência, diretoria, supervisão).
     - **Momento atual e modalidade:** Disponibilidade (CLT, PJ, MEI), preferência de modalidade (Remoto, Híbrido, Presencial) e cidades aceitáveis.
     - **Tabela de Recrutadores a Pesquisar (opcional):** Uma tabela markdown simples listando recrutadores para o sistema enriquecer automaticamente:

       ```markdown
       ## Recrutadores para Pesquisa

       | Nome | Cargo / Headline no LinkedIn | Local | Empresa Atual | Foco de Recrutamento |
       | :--- | :--- | :--- | :--- | :--- |
       | Maria Santos | Especialista em Talent Acquisition | São Paulo, SP | Pendente | Administrativo, Financeiro |
       ```

3. **Gerar os Bancos de Dados Locais em JSON via CLI:**

   ```powershell
   linkedin-researcher profile build
   ```

   O sistema processará o PDF e o Markdown, populando automaticamente `data/perfil_candidato.json` e `data/recrutadores.json`.

---

## 🏗️ Arquitetura Modular do Código (`src/linkedin_researcher/`)

- `config.py`: Carregamento e validação de configurações via variáveis de ambiente (`.env`), timeouts, limites de cota LLM e detecção dinâmica do currículo `.pdf` e do markdown correspondente.
- `models.py`: Modelos de domínio fortemente tipados com validação Pydantic v2 (`CandidateProfile`, `Recruiter`, `Company`, `Job`, `SuggestedMessage`).
- `storage.py`: Camada de persistência local atômica em JSON (`data/`), garantindo integridade de escrita e deduplicação sem manter dados fixos no código Python.
- `browser/`:
  - `browser_manager.py`: Inicialização e ciclo de vida do Playwright (`BrowserContext`, Chrome persistente, anti-detection flags).
  - `session_manager.py`: Login interativo assistido e verificação de integridade da sessão autenticada.
  - `linkedin_pages.py`: Locators resilientes com acessibilidade (ARIA roles/labels) e extração de dados brutos.
- `research/`:
  - `recruiter_research.py`: Orquestração de pesquisa, enriquecimento institucional de recrutadores e resolução de pendências.
  - `company_research.py`: Extração de dados corporativos de empresas (setor, sede, website, modelo de trabalho).
  - `job_research.py`: Descoberta, busca e coleta de vagas por palavras-chave ou URL direta.
- `analysis/`:
  - `curriculum_profile.py`: Normalização de currículo em PDF, parser de markdown e gerador estruturado de JSONs.
  - `job_matching.py`: Motor explicável de classificação de aderência (Alta, Média, Baixa) com pontos fortes e lacunas.
  - `ranking.py`: Ordenação de oportunidades por aderência, modelo de trabalho e data.
- `messaging/`:
  - `message_generator.py`: Elaboração de mensagens cordiais em primeira pessoa para revisão humana manual.
- `cli.py`: Interface de linha de comando única (`linkedin-researcher`).

---

## 📁 Estrutura de Diretórios

```text
python-linkedin-researcher/
├── AGENTS.md                          # Diretrizes para agentes autônomos (Google Antigravity)
├── README.md                          # Guia oficial de uso e arquitetura do projeto
├── pyproject.toml                     # Metadados do pacote linkedin-researcher e dependências
├── requirements.txt                   # Congelamento de dependências do ambiente virtual
├── .env.example                       # Modelo de variáveis de ambiente
├── .gitignore                         # Blindagem estrita contra commit de dados pessoais
├── curriculum/
│   ├── .gitkeep
│   └── <Candidato>.pdf                # Currículo do candidato ativo (ignorado pelo Git)
├── data/
│   ├── .gitkeep
│   ├── informacoes_adicionais.template.md  # Modelo de diretrizes e recrutadores para cópia
│   ├── perfil_candidato.template.json      # Modelo de schema do perfil do candidato
│   ├── recrutadores.template.json          # Modelo de schema de recrutadores
│   ├── empresas.template.json              # Modelo de schema de empresas
│   ├── vagas.template.json                 # Modelo de schema de vagas
│   ├── contatos.template.json              # Modelo de schema de contatos
│   ├── <Candidato>.md                 # Diretrizes e recrutadores locais (ignorado pelo Git)
│   └── *.json                         # Bases de dados geradas localmente (ignoradas pelo Git)
├── docs/                              # Manuais detalhados de arquitetura, segurança e código
├── .agents/                           # Skills, regras e agentes padronizados para Agy
├── src/linkedin_researcher/             # Código-fonte da aplicação
├── tests/                             # Suíte de testes automatizados unitários e de integração
├── output/                            # Relatórios e rascunhos de mensagens (ignorados pelo Git)
└── logs/                              # Logs estruturados de execução (ignorados pelo Git)
```

---

## 🚀 Guia Prático de Execução

### 1. Preparar o Ambiente Virtual

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\pip install -e .
```

### 2. Validar o Ambiente (`doctor`)

```powershell
linkedin-researcher doctor
```

### 3. Configurar e Gerar Perfil do Candidato

```powershell
# 1. Gerar os JSONs a partir do PDF em curriculum/ e do MD em data/
linkedin-researcher profile build

# 2. Inspecionar o perfil carregado
linkedin-researcher profile show
```

### 4. Autenticação Inicial no LinkedIn (Login Manual Assistido)

```powershell
linkedin-researcher browser login
```

Uma janela do navegador será aberta utilizando a pasta local `.playwright-profile/`. Conclua seu login e verificação em duas etapas normalmente. Uma vez no feed do LinkedIn, a sessão permanecerá salva localmente para os próximos comandos.

### 5. Operações de Prospecção e Pesquisa

```powershell
# Listar recrutadores cadastrados
linkedin-researcher recruiters list

# Pesquisar e enriquecer dados dos recrutadores (obter empresa atual, vínculo, contexto)
linkedin-researcher recruiters research --id rec-01-fulado-de-tal
linkedin-researcher recruiters research --all

# Listar e pesquisar empresas
linkedin-researcher companies list
linkedin-researcher companies research --id comp-empresa-do-fulano
linkedin-researcher companies research --all

# Pesquisar vagas no LinkedIn por cargo e localização
linkedin-researcher jobs search --keywords "Assistente Administrativo" --location "Porto Alegre e Região" --limit 5

# Cadastrar vaga por URL direta ou manualmente
linkedin-researcher jobs add-url --url "https://www.linkedin.com/jobs/view/<ID>/"
linkedin-researcher jobs add --title "Assistente Financeiro" --company "Empresa X" --url "https://..."

# Avaliar aderência explicável da vaga em 7 dimensões (com pré-filtro local de exclusão)
linkedin-researcher jobs match --id <job_id>
linkedin-researcher jobs match --all
linkedin-researcher jobs match --all --offline  # força modo 100% determinístico local

# Listar vagas com filtros de nível, modalidade e ranking
linkedin-researcher jobs list
linkedin-researcher jobs list --level alta --ranked
linkedin-researcher jobs list --model remoto
```

### 6. Rascunhos de Mensagens e Relatórios (Human-in-the-Loop)

> [!IMPORTANT]
> **Controle Humano Obrigatório**: O sistema **nunca** envia mensagens ou convites automaticamente no LinkedIn. Todos os textos são gerados como rascunhos para leitura, personalização e envio manual a partir da sua conta.

```powershell
# Gerar rascunho de primeiro contato para um recrutador específico
linkedin-researcher messages draft --recruiter-id rec-01-fulano-de-tal

# Gerar rascunho vinculando a uma vaga específica cadastrada
linkedin-researcher messages draft --recruiter-id rec-01-fulano-de-tal --job-id job-empresa-x-assistente

# Gerar rascunhos para todos os recrutadores cadastrados (modo determinístico ou híbrido Gemini)
linkedin-researcher messages draft --all
linkedin-researcher messages draft --all --offline  # força templates determinísticos locais

# Listar mensagens geradas e seus status de revisão
linkedin-researcher messages list
linkedin-researcher messages list --recruiter-id rec-01-fulano-de-tal

# Atualizar status de revisão após conferência manual
linkedin-researcher messages review --id msg-rec-01-fulano-de-tal --status aprovado

# Registrar envio manual feito via LinkedIn
linkedin-researcher messages review --id msg-rec-01-fulano-de-tal --mark-sent

# Gerar relatório executivo consolidado com panorama de recrutadores, vagas e contatos
linkedin-researcher report
linkedin-researcher report --output output/meu_relatorio.md
```

Os rascunhos detalhados ficam disponíveis tanto na base estruturada `data/contatos.json` quanto em arquivos individuais de fácil leitura e edição em `output/mensagens/<slug-recrutador>.md` (com checklist de verificação humana). O relatório executivo é gerado em `output/relatorio_consolidado.md`.

---

## 🧪 Testes Automatizados

A suíte de testes unitários foi construída para rodar com fixtures isoladas e mocks que nunca realizam requisições reais à rede:

```powershell
.\.venv\Scripts\pytest -q
# ou se estiver utilizando o token optimizer RTK:
rtk pytest
```
