"""Interface de Linha de Comando (CLI) — LinkedIn Researcher & Career Assistant."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from importlib.metadata import version as pkg_version
from pathlib import Path

from linkedin_researcher.analysis.curriculum_profile import (
    build_profile_and_recruiters_from_cv_and_md,
    load_candidate_profile,
    save_candidate_profile,
)
from linkedin_researcher.analysis.job_matching import (
    match_all_jobs,
    match_job,
)
from linkedin_researcher.analysis.ranking import (
    filter_jobs_by_match_level,
    filter_jobs_by_work_model,
    rank_jobs,
)
from linkedin_researcher.browser.session_manager import (
    ManualInterventionRequiredError,
    interactive_login,
)
from linkedin_researcher.config import load_config
from linkedin_researcher.logging_config import setup_logging
from linkedin_researcher.messaging.message_generator import (
    generate_all_drafts,
    generate_consolidated_report,
    generate_message_draft,
    review_message,
)
from linkedin_researcher.models import MatchLevel, ReviewStatus
from linkedin_researcher.research.company_research import (
    research_companies,
    research_company_by_id,
)
from linkedin_researcher.research.job_research import (
    register_job_by_url,
    register_job_manually,
    research_jobs,
)
from linkedin_researcher.research.recruiter_research import (
    manually_update_recruiter,
    research_recruiters,
)
from linkedin_researcher.storage import JsonStorage


def run_doctor() -> int:
    """Valida configuração, diretórios, currículo em PDF, dados e dependências principais."""
    cfg = load_config()
    logger = setup_logging(cfg.logs_dir, cfg.log_level)
    logger.info("Executando diagnóstico do ambiente (doctor)...")

    storage = JsonStorage(cfg)
    recruiters = storage.seed_initial_recruiters()
    profile = load_candidate_profile(cfg)

    checks: list[tuple[str, bool, str]] = [
        ("Raiz do projeto", cfg.project_root.exists(), str(cfg.project_root)),
        (
            "Documentação do projeto (README.md)",
            (cfg.project_root / "README.md").exists(),
            "README.md",
        ),
        ("Currículo em PDF", cfg.curriculum_path.exists(), str(cfg.curriculum_path)),
        (
            "Informações adicionais do candidato",
            cfg.candidate_additional_info_file.exists(),
            str(cfg.candidate_additional_info_file),
        ),
        (
            "Perfil do candidato configurado",
            len(profile.experiences) > 0,
            f"{profile.full_name} ({len(profile.experiences)} experiências)",
        ),
        ("Diretório de dados (data/)", cfg.data_dir.exists(), str(cfg.data_dir)),
        (
            "Recrutadores cadastrados",
            len(recruiters) >= 1,
            f"{len(recruiters)} recrutadores em {cfg.recruiters_file.name}",
        ),
        ("Diretório de saída (output/)", cfg.output_dir.exists(), str(cfg.output_dir)),
        ("Diretório de logs (logs/)", cfg.logs_dir.exists(), str(cfg.logs_dir)),
        (
            "Skill oficial playwright-cli (.agents)",
            (cfg.project_root / ".agents" / "skills" / "playwright-cli" / "SKILL.md").exists(),
            ".agents/skills/playwright-cli/SKILL.md",
        ),
        (
            "Skill integrada playwright-python (.agents)",
            (cfg.project_root / ".agents" / "skills" / "playwright-python" / "SKILL.md").exists(),
            ".agents/skills/playwright-python/SKILL.md",
        ),
        (
            "Rules padronizadas (.agents/rules)",
            (cfg.project_root / ".agents" / "rules").exists(),
            ".agents/rules/",
        ),
        (
            "Agents padronizados (.agents/agents)",
            (cfg.project_root / ".agents" / "agents").exists(),
            ".agents/agents/",
        ),
        (
            "Modelo Gemini padrão configurado",
            bool(cfg.gemini_model),
            (
                f"{cfg.gemini_model} (max {cfg.gemini_max_calls_per_run} chamadas/execução; "
                f"GEMINI_API_KEY={'configurada' if cfg.has_gemini_api_key else 'opcional/offline'})"
            ),
        ),
    ]

    for pkg in ("google-genai", "playwright", "pydantic", "python-dotenv", "pypdf"):
        try:
            ver = pkg_version(pkg)
            checks.append((f"Pacote {pkg}", True, f"v{ver}"))
        except Exception as exc:  # pragma: no cover
            checks.append((f"Pacote {pkg}", False, str(exc)))

    all_ok = True
    print("\n=== Diagnóstico LinkedIn Researcher (doctor) ===")
    for label, ok, detail in checks:
        status = "OK" if ok else "PENDENTE/ERRO"
        if not ok:
            all_ok = False
        print(f"[{status}] {label}: {detail}")

    return 0 if all_ok else 1


def run_profile_show() -> int:
    """Exibe as informações do perfil do candidato ativo."""
    cfg = load_config()
    profile = load_candidate_profile(cfg)
    print("\n=== Perfil Ativo do Candidato ===")
    print(f"Nome completo: {profile.full_name}")
    print(f"Localização: {profile.location}")
    print(f"LinkedIn: {profile.linkedin_url}")
    print(f"Formação: {profile.education}")
    print(f"Disponibilidade: {', '.join(profile.contract_availability)}")
    print(f"Modalidade preferida: {profile.preferred_work_model}")
    print(f"Cargos-alvo primários: {', '.join(profile.target_roles_primary)}")
    print(f"Cargos-alvo expandidos: {', '.join(profile.target_roles_expanded)}")
    print(f"Cargos excluídos: {', '.join(profile.excluded_roles_and_levels)}")
    print(
        f"Competências comprovadas ({len(profile.proven_competencies)}): "
        f"{', '.join(profile.proven_competencies[:6])}..."
    )
    print(f"\nExperiências cadastradas ({len(profile.experiences)}):")
    for exp in profile.experiences:
        print(f"  - {exp.company} ({exp.period_pdf}): {exp.positioning_role}")
    origem = (
        cfg.candidate_profile_file
        if cfg.candidate_profile_file.exists()
        else "perfil padrão embutido"
    )
    print(f"\nArquivo de configuração: {origem}")
    if profile.additional_info:
        print(f"Informações adicionais: {cfg.candidate_additional_info_file} (carregadas)")
    return 0


def run_profile_init() -> int:
    """Cria arquivos de perfil e informações adicionais a partir dos templates se não existirem."""
    cfg = load_config()
    target = cfg.candidate_profile_file
    if target.exists():
        print(f"[AVISO] O arquivo de perfil já existe em: {target}")
    else:
        template = cfg.candidate_profile_template_file
        if template.exists():
            target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[OK] Perfil inicial criado a partir do modelo em: {target}")
        else:
            profile = load_candidate_profile(cfg)
            save_candidate_profile(profile, target)
            print(f"[OK] Perfil inicial criado em: {target}")

    add_target = cfg.candidate_additional_info_file
    add_template = cfg.candidate_additional_info_template_file
    if not add_target.exists() and add_template.exists():
        add_target.write_text(add_template.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[OK] Arquivo de informações adicionais criado em: {add_target}")

    print("Preencha os campos com as informações e preferências do candidato.")
    return 0


def run_profile_build(pdf_path: Path | None = None, md_path: Path | None = None) -> int:
    """Gera arquivos JSON a partir do currículo PDF e arquivo MD de informações adicionais."""
    cfg = load_config()
    target_pdf = pdf_path or cfg.curriculum_path
    if not target_pdf or not target_pdf.exists():
        print(f"[ERRO] Currículo em PDF não encontrado em: {target_pdf}")
        print("Coloque o arquivo .pdf do currículo dentro da pasta curriculum/.")
        return 1

    profile, recruiters = build_profile_and_recruiters_from_cv_and_md(
        pdf_path=target_pdf,
        md_path=md_path,
        config=cfg,
    )
    print("\n=== Geração de Arquivos JSON de Perfil e Recrutadores ===")
    print(f"[OK] Currículo processado: {target_pdf.name}")
    print(f"[OK] Perfil salvo em: {cfg.candidate_profile_file}")
    print(f"  -> Candidato: {profile.full_name}")
    print(f"  -> Localização: {profile.location}")
    print(
        f"  -> Cargos-alvo: {len(profile.target_roles_primary)} primários, "
        f"{len(profile.target_roles_expanded)} expandidos"
    )
    print(f"  -> Informações adicionais: {'Carregadas' if profile.additional_info else 'Nenhuma'}")
    print(f"[OK] Recrutadores atualizados em: {cfg.recruiters_file}")
    print(f"  -> Total de recrutadores extraídos do MD: {len(recruiters)}")
    for r in recruiters:
        print(f"     - {r.name} ({r.id}) — {r.current_title[:60]}")
    return 0


def run_recruiters_list() -> int:
    """Lista os recrutadores cadastrados em data/recrutadores.json."""
    cfg = load_config()
    setup_logging(cfg.logs_dir, cfg.log_level)
    storage = JsonStorage(cfg)
    recruiters = storage.seed_initial_recruiters()

    print(f"\n=== Recrutadores Cadastrados ({len(recruiters)}) ===")
    for rec in recruiters:
        status = "Confirmada" if rec.company_verified else "A confirmar"
        print(
            f"- [{rec.id}] {rec.name} | Empresa: {rec.current_company} ({status}) | "
            f"Local: {rec.location}\n"
            f"  Título: {rec.current_title}\n"
            f"  URL: {rec.linkedin_url or 'Pendente'}"
        )
    return 0


def run_companies_list() -> int:
    """Lista as empresas cadastradas em data/empresas.json."""
    cfg = load_config()
    setup_logging(cfg.logs_dir, cfg.log_level)
    storage = JsonStorage(cfg)
    companies = storage.list_companies()

    print(f"\n=== Empresas Cadastradas ({len(companies)}) ===")
    if not companies:
        print("Nenhuma empresa cadastrada ainda. Execute a pesquisa de recrutadores ou vagas.")
        return 0

    for comp in companies:
        print(
            f"- [{comp.id}] {comp.name} | Setor: {comp.industry} | "
            f"Local: {comp.location} | URL: {comp.linkedin_url or '-'}"
        )
    return 0


def run_jobs_list(
    level_filter: str | None = None,
    model_filter: str | None = None,
    ranked: bool = False,
) -> int:
    """Lista as vagas cadastradas em data/vagas.json com suporte a filtros e ranking."""
    cfg = load_config()
    setup_logging(cfg.logs_dir, cfg.log_level)
    storage = JsonStorage(cfg)
    jobs = storage.list_jobs()

    if not jobs:
        print("\n=== Vagas Cadastradas (0) ===")
        print("Nenhuma vaga registrada ainda. Use 'jobs search' ou 'jobs add-url' para coletar.")
        return 0

    if level_filter:
        clean_lvl = level_filter.strip().casefold()
        if "alta" in clean_lvl:
            jobs = filter_jobs_by_match_level(jobs, min_level=MatchLevel.HIGH)
        elif "med" in clean_lvl:
            jobs = filter_jobs_by_match_level(jobs, min_level=MatchLevel.MEDIUM)
        elif "baix" in clean_lvl:
            jobs = filter_jobs_by_match_level(jobs, min_level=MatchLevel.LOW)

    if model_filter:
        jobs = filter_jobs_by_work_model(jobs, allowed_models=[model_filter])

    if ranked:
        profile = load_candidate_profile(cfg)
        jobs = rank_jobs(jobs, profile)

    filter_info: list[str] = []
    if level_filter:
        filter_info.append(f"nível>={level_filter}")
    if model_filter:
        filter_info.append(f"modalidade={model_filter}")
    if ranked:
        filter_info.append("ranqueadas")
    filter_desc = f" [{', '.join(filter_info)}]" if filter_info else ""

    print(f"\n=== Vagas Cadastradas ({len(jobs)}){filter_desc} ===")
    if not jobs:
        print("Nenhuma vaga corresponde aos filtros aplicados.")
        return 0

    for j in jobs:
        match_str = j.match_level.value if j.match_level else "Não avaliada"
        score_str = f"{j.match_score:.0f}/100" if j.match_score is not None else "-"
        print(
            f"- [{j.id}] {j.title} | Empresa: {j.company} | "
            f"Local: {j.location} | Modalidade: {j.work_model}"
        )
        print(
            f"  Contratação: {j.contract_type} | Salário: {j.salary_range} | "
            f"Aderência: {match_str} ({score_str})"
        )
        if j.strengths:
            print(f"  + Pontos fortes: {'; '.join(j.strengths[:2])}")
        if j.gaps:
            print(f"  - Pontos de atenção: {'; '.join(j.gaps[:2])}")
        print(f"  URL: {j.application_url}")
    return 0


def run_jobs_match(
    job_id: str | None = None,
    match_all: bool = False,
    refresh: bool = False,
    force_offline: bool = False,
) -> int:
    """Executa a análise explicável de aderência de uma vaga ou de todas as cadastradas."""
    cfg = load_config()
    setup_logging(cfg.logs_dir, cfg.log_level)

    if match_all or job_id == "all":
        print("\n=== Avaliando Aderência de Todas as Vagas ===")
        updated_list = match_all_jobs(cfg, refresh=refresh, force_offline=force_offline)
        if not updated_list:
            print("[AVISO] Nenhuma vaga cadastrada para avaliar. Use 'jobs search' ou 'jobs add'.")
            return 0
        ranked = rank_jobs(updated_list)
        for j in ranked:
            score_str = f"{j.match_score:.0f}/100" if j.match_score is not None else "-"
            print(f"\n- [{j.id}] {j.title} ({j.company}) -> {j.match_level.value} ({score_str})")
            if j.strengths:
                print(f"  + Pontos fortes: {'; '.join(j.strengths[:3])}")
            if j.gaps:
                print(f"  - Pontos de atenção: {'; '.join(j.gaps[:2])}")
        print(
            f"\n[OK] {len(updated_list)} vaga(s) processada(s). "
            f"Relatório atualizado em: output/oportunidades/resumo_vagas.md"
        )
        return 0

    if not job_id:
        print("[ERRO] Informe --id <id> da vaga ou use --all para avaliar todas.")
        return 1

    print(f"\n=== Avaliando Aderência da Vaga: {job_id} ===")
    j = match_job(cfg, job_id=job_id, refresh=refresh, force_offline=force_offline)
    score_str = f"{j.match_score:.0f}/100" if j.match_score is not None else "-"
    print(f"[OK] Vaga analisada com sucesso: {j.title} ({j.company})")
    print(f"  -> Classificação: {j.match_level.value} (Score: {score_str})")
    print(f"  -> Modalidade: {j.work_model} | Localização: {j.location}")
    print("  -> Pontos Fortes:")
    if j.strengths:
        for s in j.strengths:
            print(f"     + {s}")
    else:
        print("     (Nenhum ponto forte identificado)")
    print("  -> Pontos de Atenção / Lacunas:")
    if j.gaps:
        for g in j.gaps:
            print(f"     - {g}")
    else:
        print("     (Nenhuma lacuna crítica observada)")
    print("  -> Relatório atualizado em: output/oportunidades/resumo_vagas.md")
    return 0


def run_messages_list(recruiter_id: str | None = None) -> int:
    """Lista as mensagens cadastradas em data/contatos.json."""
    cfg = load_config()
    setup_logging(cfg.logs_dir, cfg.log_level)
    storage = JsonStorage(cfg)
    messages = storage.list_messages(recruiter_id=recruiter_id)

    filter_desc = f" para o recrutador '{recruiter_id}'" if recruiter_id else ""
    print(f"\n=== Mensagens Sugeridas Cadastradas ({len(messages)}){filter_desc} ===")
    if not messages:
        print("Nenhuma mensagem gerada ainda. Use 'messages draft --recruiter-id <id>' ou '--all'.")
        return 0

    for m in messages:
        rec = storage.get_recruiter(m.recruiter_id)
        rec_name = rec.name if rec else m.recruiter_id
        sent_info = f"Sim ({m.sent_at[:10]})" if m.sent_by_user and m.sent_at else "Não"
        preview = m.message_text.replace("\n", " ")[:80] + "..."
        slug = re.sub(r"[^a-z0-9]+", "-", m.recruiter_id.casefold()).strip("-")
        print(f"- [{m.id}] Destinatário: {rec_name} ({m.recruiter_id})")
        print(f"  Status de Revisão: {m.review_status.value} | Enviada manualmente: {sent_info}")
        print(f"  Contexto: {m.context}")
        print(f"  Prévia: \"{preview}\"")
        print(f"  Arquivo Markdown: output/mensagens/{slug}.md\n")
    return 0


def run_messages_draft(
    recruiter_id: str | None = None,
    draft_all: bool = False,
    job_id: str | None = None,
    refresh: bool = False,
    force_offline: bool = False,
) -> int:
    """Gera rascunho de mensagem para um recrutador ou para todos os cadastrados."""
    cfg = load_config()
    setup_logging(cfg.logs_dir, cfg.log_level)

    if draft_all or recruiter_id == "all":
        print("\n=== Gerando Rascunhos de Mensagens para Todos os Recrutadores ===")
        msgs = generate_all_drafts(cfg, refresh=refresh, force_offline=force_offline)
        storage = JsonStorage(cfg)
        for m in msgs:
            rec = storage.get_recruiter(m.recruiter_id)
            rec_name = rec.name if rec else m.recruiter_id
            print(f"- [{m.id}] {rec_name} -> {m.review_status.value}")
        print(
            f"\n[OK] {len(msgs)} rascunho(s) pronto(s) para revisão em "
            "output/mensagens/ e data/contatos.json."
        )
        return 0

    if not recruiter_id:
        print("[ERRO] Informe --recruiter-id <id> ou use --all para todos os cadastrados.")
        return 1

    print(f"\n=== Gerando Rascunho de Mensagem para: {recruiter_id} ===")
    msg = generate_message_draft(
        config=cfg,
        recruiter_id=recruiter_id,
        job_id=job_id,
        refresh=refresh,
        force_offline=force_offline,
    )
    storage = JsonStorage(cfg)
    rec = storage.get_recruiter(msg.recruiter_id)
    rec_name = rec.name if rec else msg.recruiter_id
    slug = re.sub(r"[^a-z0-9]+", "-", msg.recruiter_id.casefold()).strip("-")

    print("[OK] Rascunho gerado com sucesso!")
    print(f"  -> ID: {msg.id}")
    print(f"  -> Destinatário: {rec_name}")
    print(f"  -> Status: {msg.review_status.value} (Enviado pelo usuário: {msg.sent_by_user})")
    print(f"  -> Contexto: {msg.context}")
    print(f"  -> Arquivo Markdown: output/mensagens/{slug}.md\n")
    print("--- Texto Sugerido para Envio Manual ---")
    print(msg.message_text.strip())
    print("----------------------------------------")
    return 0


def run_messages_review(
    message_id: str,
    status_str: str | None = None,
    mark_sent: bool = False,
    notes: str | None = None,
) -> int:
    """Atualiza o status de revisão humana de uma mensagem."""
    cfg = load_config()
    setup_logging(cfg.logs_dir, cfg.log_level)

    status_map = {
        "pendente": ReviewStatus.PENDING_REVIEW,
        "aprovada": ReviewStatus.APPROVED,
        "editada": ReviewStatus.EDITED,
        "descartada": ReviewStatus.DISCARDED,
    }
    status_enum = status_map.get(status_str.strip().casefold()) if status_str else None

    if status_str and status_enum is None:
        print(
            f"[ERRO] Status inválido '{status_str}'. "
            "Use: pendente, aprovada, editada ou descartada."
        )
        return 1

    updated = review_message(
        config=cfg,
        message_id=message_id,
        status=status_enum,
        mark_sent=mark_sent,
        notes=notes,
    )
    print(f"[OK] Mensagem '{updated.id}' atualizada com sucesso.")
    print(f"  -> Status de revisão: {updated.review_status.value}")
    print(f"  -> Enviada manualmente pelo usuário: {'Sim' if updated.sent_by_user else 'Não'}")
    if updated.sent_at:
        print(f"  -> Data do envio manual: {updated.sent_at}")
    if updated.notes:
        print(f"  -> Anotações: {updated.notes}")
    return 0


def run_report(output_path: Path | None = None) -> int:
    """Gera o relatório geral consolidado do projeto."""
    cfg = load_config()
    setup_logging(cfg.logs_dir, cfg.log_level)
    report_file = generate_consolidated_report(cfg, output_path=output_path)
    print("\n=== Relatório Geral Consolidado Gerado com Sucesso ===")
    print(f"[OK] Arquivo salvo em: {report_file}")
    print("O relatório consolida perfil do candidato, vagas ranqueadas, empresas e mensagens.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin-researcher",
        description="LinkedIn Researcher & Career Assistant (Controle Humano Obrigatório)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Validar configuração, estrutura e dependências")

    # Grupo de comandos para perfil de candidato
    profile_parser = subparsers.add_parser("profile", help="Gerenciar perfil do candidato")
    profile_sub = profile_parser.add_subparsers(dest="profile_action", required=True)
    profile_sub.add_parser("show", help="Exibir o perfil ativo do candidato")
    profile_sub.add_parser("init", help="Inicializar data/perfil_candidato.json a partir do modelo")
    profile_build = profile_sub.add_parser(
        "build",
        help="Gerar arquivos JSON via currículo em PDF e arquivo MD de informações adicionais",
    )
    profile_build.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Caminho do currículo (.pdf exclusivamente; arquivos .docx são rejeitados)",
    )
    profile_build.add_argument(
        "--md",
        type=Path,
        default=None,
        help="Caminho do arquivo MD com informações adicionais e recrutadores",
    )

    browser_parser = subparsers.add_parser("browser", help="Gerenciar sessão do navegador")
    browser_sub = browser_parser.add_subparsers(dest="browser_action", required=True)
    login_p = browser_sub.add_parser("login", help="Abrir sessão autenticada para login manual")
    login_p.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Tempo máximo de espera pelo login manual em segundos (padrão: 300)",
    )

    recruiters_parser = subparsers.add_parser("recruiters", help="Operações com recrutadores")
    recruiters_sub = recruiters_parser.add_subparsers(dest="recruiters_action", required=True)
    recruiters_sub.add_parser("list", help="Listar recrutadores cadastrados")
    rec_res = recruiters_sub.add_parser(
        "research",
        help="Pesquisar um recrutador (--id <id>) ou todos os cadastrados (--all)",
    )
    rec_group = rec_res.add_mutually_exclusive_group(required=True)
    rec_group.add_argument("--id", help="ID do recrutador (ou 'all' para todos)")
    rec_group.add_argument(
        "--all",
        action="store_true",
        help="Pesquisar sequencialmente todos os recrutadores cadastrados",
    )

    rec_set_url = recruiters_sub.add_parser(
        "set-url", help="Definir manualmente a URL do perfil de um recrutador"
    )
    rec_set_url.add_argument("--id", required=True, help="ID do recrutador")
    rec_set_url.add_argument("--url", required=True, help="URL do perfil no LinkedIn")

    rec_update = recruiters_sub.add_parser(
        "update",
        help="Confirmar ou atualizar manualmente empresa, URL ou dados pendentes de um recrutador",
    )
    rec_update.add_argument("--id", required=True, help="ID do recrutador")
    rec_update.add_argument("--company", help="Nome da empresa atual do recrutador")
    rec_update.add_argument(
        "--verified",
        action="store_true",
        default=None,
        help="Marcar vínculo com a empresa como confirmado (company_verified=true)",
    )
    rec_update.add_argument("--url", help="URL do perfil no LinkedIn")
    rec_update.add_argument("--title", help="Cargo/headline atual")
    rec_update.add_argument("--location", help="Localização")
    rec_update.add_argument("--notes", help="Observação manual sobre a confirmação")

    companies_parser = subparsers.add_parser("companies", help="Operações com empresas")
    companies_sub = companies_parser.add_subparsers(dest="companies_action", required=True)
    companies_sub.add_parser("list", help="Listar empresas identificadas")
    comp_res = companies_sub.add_parser(
        "research",
        help="Pesquisar uma empresa específica (--id <id>) ou todas as cadastradas (--all)",
    )
    comp_group = comp_res.add_mutually_exclusive_group(required=True)
    comp_group.add_argument("--id", help="ID da empresa (ou 'all' para todas)")
    comp_group.add_argument(
        "--all",
        action="store_true",
        help="Pesquisar sequencialmente todas as empresas cadastradas",
    )

    jobs_parser = subparsers.add_parser("jobs", help="Operações de descoberta e coleta de vagas")
    jobs_sub = jobs_parser.add_subparsers(dest="jobs_action", required=True)
    job_list_p = jobs_sub.add_parser("list", help="Listar vagas identificadas")
    job_list_p.add_argument(
        "--level",
        choices=["alta", "media", "baixa"],
        help="Filtrar vagas por nível mínimo de aderência",
    )
    job_list_p.add_argument(
        "--model",
        help="Filtrar vagas por modalidade (ex: remoto, hibrido, presencial)",
    )
    job_list_p.add_argument(
        "--ranked",
        action="store_true",
        help="Exibir vagas ordenadas pelo ranking de aderência",
    )

    job_search = jobs_sub.add_parser("search", help="Pesquisar vagas no LinkedIn")
    job_search.add_argument(
        "--keywords",
        default="Assistente Administrativo",
        help="Palavras-chave de busca de vagas",
    )
    job_search.add_argument(
        "--location",
        default="Porto Alegre, RS",
        help="Localização desejada da vaga",
    )
    job_search.add_argument(
        "--remote", action="store_true", help="Filtrar exclusivamente por vagas remotas"
    )
    job_search.add_argument(
        "--limit", type=int, default=5, help="Quantidade máxima de vagas a coletar (padrão: 5)"
    )

    job_add_url = jobs_sub.add_parser(
        "add-url", help="Coletar e registrar vaga a partir da URL no LinkedIn"
    )
    job_add_url.add_argument("--url", required=True, help="URL da vaga no LinkedIn")

    job_add = jobs_sub.add_parser("add", help="Registrar manualmente uma vaga")
    job_add.add_argument("--title", required=True, help="Título da vaga")
    job_add.add_argument("--company", required=True, help="Nome da empresa")
    job_add.add_argument(
        "--url", required=True, help="URL da vaga para candidatura/consulta"
    )
    job_add.add_argument(
        "--location", default="a confirmar", help="Localização"
    )
    job_add.add_argument(
        "--model",
        default="a confirmar",
        help="Modalidade de trabalho (Presencial, Híbrido, Remoto)",
    )
    job_add.add_argument(
        "--contract",
        default="a confirmar",
        help="Tipo de contratação (CLT, PJ)",
    )
    job_add.add_argument(
        "--salary", default="Não informado", help="Faixa salarial informada"
    )

    job_match = jobs_sub.add_parser("match", help="Analisar aderência de uma ou todas as vagas")
    job_match_grp = job_match.add_mutually_exclusive_group(required=True)
    job_match_grp.add_argument(
        "--id", help="ID da vaga a ser analisada (ou 'all' para avaliar todas)"
    )
    job_match_grp.add_argument(
        "--all", action="store_true", help="Avaliar sequencialmente todas as vagas cadastradas"
    )
    job_match.add_argument(
        "--refresh",
        action="store_true",
        help="Reavaliar a vaga mesmo se já houver avaliação em cache",
    )
    job_match.add_argument(
        "--offline",
        action="store_true",
        help="Forçar avaliação determinística local (sem chamadas à API Gemini)",
    )

    messages_parser = subparsers.add_parser(
        "messages", help="Elaboração e revisão de mensagens para controle humano"
    )
    messages_sub = messages_parser.add_subparsers(dest="messages_action", required=True)

    msg_draft = messages_sub.add_parser("draft", help="Gerar rascunho de mensagem para revisão")
    msg_draft_grp = msg_draft.add_mutually_exclusive_group(required=True)
    msg_draft_grp.add_argument(
        "--recruiter-id", help="ID do recrutador (ou 'all' para todos)"
    )
    msg_draft_grp.add_argument(
        "--all", action="store_true", help="Gerar rascunhos para todos os recrutadores cadastrados"
    )
    msg_draft.add_argument("--job-id", help="Vincular a uma vaga específica analisada")
    msg_draft.add_argument(
        "--refresh", action="store_true", help="Forçar nova geração ignorando cache"
    )
    msg_draft.add_argument(
        "--offline", action="store_true", help="Forçar geração determinística local (sem Gemini)"
    )

    msg_list = messages_sub.add_parser("list", help="Listar mensagens e rascunhos gerados")
    msg_list.add_argument("--recruiter-id", help="Filtrar mensagens de um recrutador específico")

    msg_review = messages_sub.add_parser(
        "review", help="Atualizar status de revisão e registro manual de envio"
    )
    msg_review.add_argument("--id", required=True, help="ID da mensagem a revisar")
    msg_review.add_argument(
        "--status",
        choices=["pendente", "aprovada", "editada", "descartada"],
        help="Novo status da revisão humana",
    )
    msg_review.add_argument(
        "--mark-sent",
        action="store_true",
        help="Registrar que você enviou manualmente a mensagem pelo seu LinkedIn",
    )
    msg_review.add_argument("--notes", help="Observações ou anotações da revisão")

    report_parser = subparsers.add_parser("report", help="Gerar relatório geral consolidado")
    report_parser.add_argument(
        "--output", type=Path, default=None, help="Caminho customizado para o arquivo markdown"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config()
    setup_logging(cfg.logs_dir, cfg.log_level)

    try:
        if args.command == "doctor":
            return run_doctor()

        if args.command == "profile":
            if args.profile_action == "show":
                return run_profile_show()
            if args.profile_action == "init":
                return run_profile_init()
            if args.profile_action == "build":
                return run_profile_build(args.pdf, args.md)

        if args.command == "browser" and args.browser_action == "login":
            ok = asyncio.run(interactive_login(cfg, max_wait_seconds=args.timeout))
            return 0 if ok else 1

        if args.command == "recruiters":
            if args.recruiters_action == "list":
                return run_recruiters_list()
            if args.recruiters_action == "set-url":
                storage = JsonStorage(cfg)
                storage.seed_initial_recruiters()
                rec = storage.get_recruiter(args.id)
                if rec is None:
                    print(f"[ERRO] Recrutador '{args.id}' não encontrado.")
                    return 1
                updated = rec.model_copy(update={"linkedin_url": args.url})
                storage.upsert_recruiter(updated)
                print(f"[OK] URL de {rec.name} atualizada para: {args.url}")
                return 0
            if args.recruiters_action == "update":
                updated = manually_update_recruiter(
                    cfg,
                    recruiter_id=args.id,
                    company_name=args.company,
                    verified=args.verified,
                    linkedin_url=args.url,
                    title=args.title,
                    location=args.location,
                    notes=args.notes,
                )
                ver_label = "Confirmada" if updated.company_verified else "A confirmar"
                print(
                    f"[OK] Recrutador atualizado: {updated.name} ({updated.id})\n"
                    f"  -> Empresa: {updated.current_company} ({ver_label})\n"
                    f"  -> URL: {updated.linkedin_url or '-'}"
                )
                return 0
            if args.recruiters_action == "research":
                asyncio.run(
                    research_recruiters(
                        cfg,
                        recruiter_id=args.id,
                        research_all=bool(args.all or args.id == "all"),
                    )
                )
                return 0

        if args.command == "companies":
            if args.companies_action == "list":
                return run_companies_list()
            if args.companies_action == "research":
                if args.all or args.id == "all":
                    asyncio.run(research_companies(cfg, research_all=True))
                else:
                    comp = asyncio.run(research_company_by_id(cfg, args.id))
                    print(
                        f"[OK] Empresa atualizada: {comp.name} | Setor: {comp.industry} | "
                        f"Sede: {comp.location} | Site: {comp.website or '-'}"
                    )
                return 0

        if args.command == "jobs":
            if args.jobs_action == "list":
                return run_jobs_list(
                    level_filter=args.level,
                    model_filter=args.model,
                    ranked=args.ranked,
                )
            if args.jobs_action == "match":
                return run_jobs_match(
                    job_id=args.id,
                    match_all=bool(args.all or (args.id and args.id == "all")),
                    refresh=args.refresh,
                    force_offline=args.offline,
                )
            if args.jobs_action == "search":
                asyncio.run(
                    research_jobs(
                        cfg,
                        keywords=args.keywords,
                        location=args.location,
                        remote_only=args.remote,
                        limit=args.limit,
                    )
                )
                return 0
            if args.jobs_action == "add-url":
                job = asyncio.run(register_job_by_url(cfg, job_url=args.url))
                print(
                    f"[OK] Vaga coletada e registrada: {job.title} ({job.company})\n"
                    f"  -> ID: {job.id}\n"
                    f"  -> Localidade: {job.location} | Modalidade: {job.work_model}\n"
                    f"  -> URL: {job.application_url}"
                )
                return 0
            if args.jobs_action == "add":
                job = register_job_manually(
                    cfg,
                    title=args.title,
                    company=args.company,
                    application_url=args.url,
                    location=args.location,
                    work_model=args.model,
                    contract_type=args.contract,
                    salary_range=args.salary,
                )
                print(
                    f"[OK] Vaga registrada manualmente: {job.title} ({job.company})\n"
                    f"  -> ID: {job.id}\n"
                    f"  -> Localidade: {job.location} | Modalidade: {job.work_model}\n"
                    f"  -> URL: {job.application_url}"
                )
                return 0

        if args.command == "messages":
            if args.messages_action == "list":
                return run_messages_list(recruiter_id=args.recruiter_id)
            if args.messages_action == "draft":
                return run_messages_draft(
                    recruiter_id=args.recruiter_id,
                    draft_all=bool(args.all or (args.recruiter_id and args.recruiter_id == "all")),
                    job_id=args.job_id,
                    refresh=args.refresh,
                    force_offline=args.offline,
                )
            if args.messages_action == "review":
                return run_messages_review(
                    message_id=args.id,
                    status_str=args.status,
                    mark_sent=args.mark_sent,
                    notes=args.notes,
                )

        if args.command == "report":
            return run_report(output_path=args.output)

    except ManualInterventionRequiredError as exc:
        print(f"\n[AÇÃO HUMANA NECESSÁRIA] {exc}")
        return 2
    except Exception as exc:
        print(f"\n[ERRO] {exc}")
        return 1

    print(
        f"Comando '{args.command}' registrado. "
        "Implementação detalhada prevista para as próximas etapas do plano."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
