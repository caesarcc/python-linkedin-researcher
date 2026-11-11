# Regra 01 — Contexto Profissional Configurável e Limites Éticos

## 1. Fontes da Verdade e Perfil do Candidato

Qualquer funcionalidade, análise de vaga ou geração de mensagem deve basear-se exclusivamente em:

1. `data/perfil_candidato.json` (ou `data/perfil_candidato.template.json`), carregado dinamicamente via `load_candidate_profile()`.
2. Currículo do candidato em `curriculum/` (`.pdf`).
3. Diretrizes em `brief_projeto.template.md` (e arquivos locais de contexto quando existirem).

- **Proibido inventar dados:** Nunca invente experiências, datas, empresas, ferramentas, idiomas, resultados ou responsabilidades para o candidato ativo, nem infira vínculos não verificados de recrutadores.
- **Marcação obrigatória de pendências:** Qualquer dado não confirmado deve ser registrado como **`"a confirmar"`** ou **`"Pendente"`**.
- **Posicionamento de Cargos e Senioridade:** Seguir rigorosamente as preferências de `target_roles_primary`, `target_levels` e `excluded_roles_and_levels` cadastradas no perfil ativo do candidato (evitando cargos de gestão/diretoria quando excluídos pelo profissional).

## 2. Controle Humano Obrigatório (Inviolável)

- **PROIBIDO enviar mensagens automaticamente:** O sistema apenas salva rascunhos em `output/mensagens/` e registra em `data/contatos.json` com `review_status = "pendente_revisao"`.
- **PROIBIDO enviar convites de conexão ou candidaturas automaticamente.**
- **PROIBIDO armazenar credenciais ou dados sensíveis no Git:** Senhas, cookies, tokens de sessão, currículos em PDF e dados raspados em JSON nunca devem ser comitados no Git (protegidos via `.gitignore`).
- **PROIBIDO contornar segurança:** Nunca tente burlar login, MFA, CAPTCHA ou limites anti-bot do LinkedIn. Diante de qualquer bloqueio ou desafio, pause e solicite ação manual do usuário.
