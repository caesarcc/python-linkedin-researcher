"""Interface Web Interativa com Streamlit para o LinkedIn Researcher & Career Assistant."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
from pydantic import BaseModel, Field

from linkedin_researcher.analysis.curriculum_profile import (
    build_profile_and_recruiters_from_cv_and_md,
    load_candidate_profile,
)
from linkedin_researcher.analysis.job_matching import match_all_jobs, match_job
from linkedin_researcher.analysis.ranking import rank_jobs
from linkedin_researcher.browser.session_manager import interactive_login
from linkedin_researcher.cli import collect_doctor_checks
from linkedin_researcher.config import AppConfig, load_config
from linkedin_researcher.llm import get_llm_provider
from linkedin_researcher.logging_config import setup_logging
from linkedin_researcher.messaging.message_generator import (
    generate_all_drafts,
    generate_consolidated_report,
    generate_message_draft,
    review_message,
)
from linkedin_researcher.models import (
    CandidateProfile,
    Company,
    JobStatus,
    MatchLevel,
    Recruiter,
    ReviewStatus,
)
from linkedin_researcher.research.company_research import research_companies
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

st.set_page_config(
    page_title="LinkedIn Researcher & Career Assistant",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilização CSS personalizada
st.markdown(
    """
    <style>
    .main-header {
        font-size: 1.85rem;
        font-weight: 700;
        color: #1e3a8a;
        margin-bottom: 0.25rem;
    }
    .sub-header {
        color: #4b5563;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }
    .kpi-card {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
    }
    .badge-alta {
        background-color: #dcfce7;
        color: #15803d;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.8rem;
    }
    .badge-media {
        background-color: #fef9c3;
        color: #a16207;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.8rem;
    }
    .badge-baixa {
        background-color: #fed7aa;
        color: #c2410c;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.8rem;
    }
    .badge-descartada {
        background-color: #fee2e2;
        color: #b91c1c;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.8rem;
    }
    .badge-nao-avaliada {
        background-color: #f1f5f9;
        color: #64748b;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.8rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_app_context() -> tuple[AppConfig, JsonStorage]:
    """Carrega configuração e repositório de persistência."""
    cfg = load_config()
    setup_logging(cfg.logs_dir, cfg.log_level)
    storage = JsonStorage(cfg)
    return cfg, storage


def safe_load_candidate_profile(cfg: AppConfig) -> CandidateProfile | None:
    """Carrega o perfil do candidato ativo ou None se ainda não existir."""
    try:
        return load_candidate_profile(cfg)
    except Exception:
        return None


def has_persistent_session(profile_dir: Path) -> bool:
    """Verifica se o diretório de perfil persistente contém arquivos de sessão."""
    try:
        return profile_dir.exists() and any(profile_dir.iterdir())
    except Exception:
        return False


def render_sidebar(cfg: AppConfig, storage: JsonStorage) -> str:
    """Renderiza a barra lateral com perfil do candidato e navegação."""
    st.sidebar.markdown("### 💼 LinkedIn Assistant")
    st.sidebar.caption("Pesquisa, Matching e Abordagem Human-in-the-Loop")

    profile = safe_load_candidate_profile(cfg)
    if profile:
        st.sidebar.markdown(f"**👤 Candidato(a):** {profile.full_name}")
        st.sidebar.markdown(f"**📍 Localização:** {profile.location}")
        roles_preview = ", ".join(profile.target_roles_primary[:2])
        st.sidebar.markdown(f"**🎯 Foco:** {roles_preview}")
        st.sidebar.markdown(f"**🏠 Modalidade:** {profile.preferred_work_model}")
    else:
        st.sidebar.warning("Perfil do candidato ainda não gerado.")
        if st.sidebar.button("Gerar Perfil Agora (PDF + MD)"):
            try:
                build_profile_and_recruiters_from_cv_and_md(
                    pdf_path=cfg.curriculum_pdf_path,
                    md_path=cfg.additional_info_path if cfg.additional_info_path.exists() else None,
                    config=cfg,
                )
                st.sidebar.success("Perfil gerado!")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Erro ao gerar perfil: {e}")

    st.sidebar.divider()

    # Diagnósticos rápidos no sidebar
    has_session = has_persistent_session(cfg.user_data_dir)
    session_status = "🟢 Conectada" if has_session else "⚪ Não autenticada"
    st.sidebar.markdown(f"**Sessão LinkedIn:** {session_status}")

    if cfg.llm_provider == "ollama":
        provider = get_llm_provider(cfg)
        ollama_status = (
            "🟢 Conectado" if provider.is_available() else "⚪ Offline / Execute 'ollama pull'"
        )  # noqa: E501
        st.sidebar.markdown(f"**LLM Local (Ollama):** {ollama_status}")
        st.sidebar.caption(f"Modelo: `{cfg.ollama_model}`")
    elif cfg.llm_provider == "gemini":
        gemini_status = "🟢 Configurada" if cfg.has_gemini_api_key else "⚪ Offline / Sem chave"
        st.sidebar.markdown(f"**Gemini AI:** {gemini_status}")
        st.sidebar.caption(f"Modelo: `{cfg.gemini_model}`")
    else:
        st.sidebar.markdown("**LLM:** ⚪ Offline / Regras determinísticas")

    st.sidebar.divider()

    menu = st.sidebar.radio(
        "Navegação",
        [
            "📊 Visão Geral",
            "🎯 Vagas & Matching",
            "👥 Recrutadores",
            "🏢 Empresas",
            "✍️ Rascunhos de Mensagens",
            "📑 Relatório Consolidado",
            "⚙️ Sessão & Diagnóstico",
        ],
        index=0,
    )

    st.sidebar.divider()
    st.sidebar.caption("Controle Humano Obrigatório — Versão 0.2.0")
    return menu


def render_dashboard(cfg: AppConfig, storage: JsonStorage) -> None:
    """Aba de visão geral com métricas, resumo do perfil e ações rápidas."""
    st.markdown('<div class="main-header">📊 Visão Geral & Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Acompanhamento consolidado de oportunidades, '
        "recrutadores e rascunhos de abordagem.</div>",
        unsafe_allow_html=True,
    )

    jobs = storage.list_jobs()
    recruiters = storage.list_recruiters()
    companies = storage.list_companies()
    messages = storage.list_messages()

    evaluated_jobs = [j for j in jobs if j.match_level != MatchLevel.NOT_EVALUATED]
    high_match_jobs = [j for j in jobs if j.match_level == MatchLevel.HIGH]
    approved_messages = [m for m in messages if m.review_status == ReviewStatus.APPROVED]
    sent_messages = [m for m in messages if m.sent_by_user]

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Vagas no Radar", len(jobs))
    c2.metric("Vagas Avaliadas", len(evaluated_jobs))
    c3.metric("Alta Aderência", len(high_match_jobs))
    c4.metric("Recrutadores", len(recruiters))
    c5.metric("Empresas Mapeadas", len(companies))
    c6.metric("Mensagens Aprovadas", f"{len(approved_messages)} ({len(sent_messages)} env)")

    st.divider()

    col_actions, col_profile = st.columns([1, 1])

    with col_actions:
        st.subheader("⚡ Ações Rápidas")
        st.write("Dispare tarefas analíticas para toda a base com um clique:")

        with st.expander("⚙️ Parâmetros de Execução", expanded=False):
            col_rp1, col_rp2 = st.columns(2)
            dash_refresh = col_rp1.checkbox(
                "🔄 Forçar reanálise/regeração (--refresh)",
                value=False,
                key="dash_refresh",
            )
            dash_offline = col_rp2.checkbox(
                "⚡ Forçar modo offline determinístico (--offline)",
                value=False,
                key="dash_offline",
            )

        if st.button("📑 Gerar / Atualizar Relatório Consolidado", width="stretch"):
            with st.spinner("Compilando relatório consolidado..."):
                report_path = generate_consolidated_report(cfg)
                st.success(f"Relatório gerado em `{report_path}`!")

        if st.button("🎯 Avaliar Aderência de Todas as Vagas", width="stretch"):
            with st.spinner("Executando análise de aderência (7 dimensões)..."):
                updated = match_all_jobs(cfg, refresh=dash_refresh, force_offline=dash_offline)
                st.success(f"{len(updated)} vagas avaliadas com sucesso!")
                st.rerun()

        if st.button("✍️ Gerar Rascunhos para Todos os Recrutadores", width="stretch"):
            with st.spinner("Gerando rascunhos de abordagem para revisão humana..."):
                drafts = generate_all_drafts(cfg, refresh=dash_refresh, force_offline=dash_offline)
                st.success(f"{len(drafts)} rascunhos gerados para revisão humana!")
                st.rerun()

    with col_profile:
        st.subheader("🎯 Perfil do Candidato Ativo")
        profile = safe_load_candidate_profile(cfg)
        if profile:
            st.markdown(f"**Nome:** {profile.full_name}")
            st.markdown(f"**Localização Base:** {profile.location}")
            st.markdown(f"**Modalidade Preferida:** {profile.preferred_work_model}")
            st.markdown(f"**Cargos Primários:** {', '.join(profile.target_roles_primary)}")
            st.markdown(f"**Cargos Excluídos:** {', '.join(profile.excluded_roles_and_levels)}")
            with st.expander("Ver Competências Chave Comprovadas"):
                for comp in profile.proven_competencies:
                    st.markdown(f"- {comp}")
        else:
            st.info("Execute 'Gerar Perfil' na barra lateral.")


def render_jobs_tab(cfg: AppConfig, storage: JsonStorage) -> None:
    """Aba de exploração, pesquisa e análise de aderência de vagas."""
    st.markdown('<div class="main-header">🎯 Vagas & Matching</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Mapeamento de vagas, avaliação em 7 dimensões '
        "e justificativas explicáveis de aderência.</div>",
        unsafe_allow_html=True,
    )

    profile = safe_load_candidate_profile(cfg)
    jobs = storage.list_jobs()

    with st.expander("🎯 Avaliação de Aderência em Lote (Matching)", expanded=False):
        col_m1, col_m2, col_m3 = st.columns([1.5, 1.5, 2])
        m_refresh = col_m1.checkbox(
            "🔄 Reavaliar vagas já em cache (--refresh)",
            value=False,
            key="jobs_m_refresh",
        )
        m_offline = col_m2.checkbox(
            "⚡ Forçar offline determinístico (--offline)",
            value=False,
            key="jobs_m_offline",
        )
        m_provider_choice = col_m3.selectbox(
            "Provedor LLM:",
            ["Padrão (.env)", "Ollama (Local)", "Gemini (Nuvem)", "Offline (Regras Locais)"],
            key="jobs_m_provider",
        )
        if st.button("🚀 Avaliar Todas as Vagas com estes Parâmetros", width="stretch"):
            provider_override = None
            if m_provider_choice == "Ollama (Local)":
                provider_override = "ollama"
            elif m_provider_choice == "Gemini (Nuvem)":
                provider_override = "gemini"
            elif m_provider_choice == "Offline (Regras Locais)":
                provider_override = "offline"

            chosen_provider = (
                get_llm_provider(cfg, provider_override=provider_override)
                if provider_override
                else None
            )

            with st.spinner("Executando avaliação de aderência para todas as vagas..."):
                updated = match_all_jobs(
                    cfg,
                    refresh=m_refresh,
                    force_offline=m_offline,
                    llm_provider=chosen_provider,
                )
                st.success(f"{len(updated)} vaga(s) processada(s) com sucesso!")
                st.rerun()

    # Barra superior de filtros
    col_f1, col_f2, col_f3, col_f4 = st.columns([1.5, 1.5, 2, 1.5])
    with col_f1:
        level_filter = st.selectbox(
            "Filtrar Aderência",
            ["Todas", "Alta", "Média", "Baixa", "Descartada", "Não avaliada"],
            index=0,
        )
    with col_f2:
        model_filter = st.selectbox(
            "Modalidade",
            ["Todas", "Remoto", "Híbrido", "Presencial"],
            index=0,
        )
    with col_f3:
        search_query = st.text_input("Buscar por cargo ou empresa", "")
    with col_f4:
        sort_by_score = st.checkbox("Ordenar por Score", value=True)

    # Filtragem
    filtered_jobs = jobs
    if level_filter == "Alta":
        filtered_jobs = [j for j in filtered_jobs if j.match_level == MatchLevel.HIGH]
    elif level_filter == "Média":
        filtered_jobs = [j for j in filtered_jobs if j.match_level == MatchLevel.MEDIUM]
    elif level_filter == "Baixa":
        filtered_jobs = [j for j in filtered_jobs if j.match_level == MatchLevel.LOW]
    elif level_filter == "Descartada":
        filtered_jobs = [j for j in filtered_jobs if j.status == JobStatus.DISCARDED]
    elif level_filter == "Não avaliada":
        filtered_jobs = [j for j in filtered_jobs if j.match_level == MatchLevel.NOT_EVALUATED]

    if model_filter != "Todas":
        val = model_filter.lower()
        filtered_jobs = [
            j
            for j in filtered_jobs
            if (
                j.work_model
                and val in j.work_model.lower()
                or (j.location and val in j.location.lower())
            )
        ]

    if search_query.strip():
        q = search_query.casefold()
        filtered_jobs = [
            j
            for j in filtered_jobs
            if q in j.title.casefold()
            or q in j.company.casefold()
            or (j.description and q in j.description.casefold())
        ]

    if sort_by_score:
        filtered_jobs = rank_jobs(filtered_jobs, profile)

    st.write(f"Exibindo **{len(filtered_jobs)}** de **{len(jobs)}** vagas cadastradas:")

    # Cards de vagas
    for job in filtered_jobs:
        with st.container(border=True):
            col_info, col_match, col_btn = st.columns([3, 1.5, 1.5])
            with col_info:
                st.markdown(f"### [{job.title}]({job.application_url})")
                st.markdown(
                    f"🏢 **{job.company}** &nbsp;|&nbsp; "
                    f"📍 **{job.location or 'Não informada'}** &nbsp;|&nbsp; "
                    f"💼 **{job.work_model or 'A confirmar'}**"
                )
            with col_match:
                score_txt = f" ({job.match_score:.0f}/100)" if job.match_score is not None else ""
                if job.status == JobStatus.DISCARDED:
                    st.markdown(
                        '<span class="badge-descartada">🔴 Descartada</span>',
                        unsafe_allow_html=True,
                    )
                elif job.match_level == MatchLevel.HIGH:
                    st.markdown(
                        f'<span class="badge-alta">🟢 Alta Aderência{score_txt}</span>',
                        unsafe_allow_html=True,
                    )
                elif job.match_level == MatchLevel.MEDIUM:
                    st.markdown(
                        f'<span class="badge-media">🟡 Média Aderência{score_txt}</span>',
                        unsafe_allow_html=True,
                    )
                elif job.match_level == MatchLevel.LOW:
                    st.markdown(
                        f'<span class="badge-baixa">🟠 Baixa Aderência{score_txt}</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<span class="badge-nao-avaliada">⚪ Não avaliada</span>',
                        unsafe_allow_html=True,
                    )

            with col_btn:
                btn_key = f"match_btn_{job.id}"
                if st.button("Avaliar Agora", key=btn_key, width="stretch"):
                    with st.spinner(f"Avaliando {job.title}..."):
                        updated = match_job(cfg, job.id, refresh=True)
                        st.toast(
                            f"Vaga avaliada: {updated.match_level.value} "
                            f"({updated.match_score or 0:.0f}/100)"
                        )
                        st.rerun()

            # Detalhes explicáveis
            if job.strengths or job.gaps:
                with st.expander("🔍 Justificativa e Análise de Compatibilidade"):
                    col_s, col_g = st.columns(2)
                    with col_s:
                        st.markdown("**Pontos Fortes Identificados:**")
                        for s in job.strengths:
                            st.markdown(f"- ✅ {s}")
                    with col_g:
                        st.markdown("**Lacunas ou Pontos de Atenção:**")
                        for g in job.gaps:
                            st.markdown(f"- ⚠️ {g}")

            if job.description:
                with st.expander("📄 Descrição Completa da Vaga"):
                    st.write(job.description)

    st.divider()

    # Seções de adição de novas vagas
    t1, t2 = st.tabs(["➕ Cadastrar Vaga por URL / Manual", "🔎 Pesquisar Vagas no LinkedIn"])
    with t1:
        st.subheader("Cadastrar Nova Oportunidade")
        c_url, c_btn = st.columns([4, 1])
        url_input = c_url.text_input("URL da Vaga no LinkedIn (jobs/view/<ID>):")
        if c_btn.button("Cadastrar via URL", width="stretch"):
            if url_input.strip():
                try:
                    with st.spinner("Processando e registrando vaga..."):
                        new_job = asyncio.run(register_job_by_url(cfg, job_url=url_input.strip()))
                        st.success(f"Vaga cadastrada com sucesso: {new_job.title}!")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao cadastrar vaga: {e}")
            else:
                st.warning("Informe uma URL válida do LinkedIn.")

        with st.expander("Ou cadastrar manualmente"):
            with st.form("manual_job_form"):
                m_title = st.text_input("Título do Cargo *")
                m_comp = st.text_input("Empresa *")
                m_url = st.text_input("URL (opcional)")
                m_loc = st.text_input("Localização", value="Porto Alegre e Região")
                m_mod = st.selectbox(
                    "Modalidade",
                    ["Híbrido", "Remoto", "Presencial", "Não informada"],
                )
                m_desc = st.text_area("Descrição da Vaga")
                sub = st.form_submit_button("Salvar Vaga")
                if sub:
                    if not m_title.strip() or not m_comp.strip():
                        st.error("Título e Empresa são obrigatórios.")
                    else:
                        dummy_url = (
                            f"https://www.linkedin.com/jobs/view/{int(datetime.now().timestamp())}"
                        )
                        reg = register_job_manually(
                            config=cfg,
                            title=m_title.strip(),
                            company=m_comp.strip(),
                            application_url=m_url.strip() if m_url.strip() else dummy_url,
                            location=m_loc.strip(),
                            work_model=m_mod,
                            description=m_desc.strip(),
                        )
                        st.success(f"Vaga '{reg.title}' cadastrada!")
                        st.rerun()

    with t2:
        st.subheader("Pesquisa Automatizada de Vagas no LinkedIn (Playwright)")
        st.info(
            "Executa uma pesquisa estruturada via Playwright e cadastra os cards encontrados. "
            "Requer sessão autenticada do LinkedIn."
        )
        col_k, col_l, col_q, col_b = st.columns([2, 2, 1, 1.5])
        s_keywords = col_k.text_input("Cargo ou Palavra-chave", value="Assistente Administrativo")
        s_loc = col_l.text_input("Localização", value="Porto Alegre e Região")
        s_limit = col_q.number_input("Limite", min_value=1, max_value=20, value=5)
        if col_b.button("Buscar Vagas", width="stretch"):
            with st.spinner("Buscando vagas no LinkedIn via Playwright..."):
                try:
                    found = asyncio.run(
                        research_jobs(
                            cfg,
                            keywords=s_keywords,
                            location=s_loc,
                            limit=int(s_limit),
                        )
                    )
                    st.success(f"Busca finalizada! {len(found)} vagas capturadas e registradas.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro na pesquisa de vagas: {e}")


def render_recruiters_tab(cfg: AppConfig, storage: JsonStorage) -> None:
    """Aba de recrutadores e profissionais de R&S."""
    st.markdown('<div class="main-header">👥 Recrutadores & Contatos</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Mapeamento de recrutadores, headhunters '
        "e especialistas em atração de talentos.</div>",
        unsafe_allow_html=True,
    )

    storage.seed_initial_recruiters()
    recruiters = storage.list_recruiters()

    tab_list, tab_research, tab_edit, tab_add = st.tabs(
        [
            "👥 Lista de Recrutadores",
            "🔍 Pesquisar no LinkedIn (Playwright)",
            "✏️ Atualizar Dados / URL",
            "➕ Cadastrar Manualmente",
        ]
    )

    with tab_list:
        st.write(f"Total de recrutadores cadastrados: **{len(recruiters)}**")
        for rec in recruiters:
            with st.container(border=True):
                col_r_info, col_r_comp, col_r_actions = st.columns([3, 2, 1.5])
                with col_r_info:
                    st.markdown(f"### {rec.name}")
                    st.markdown(f"**Título:** {rec.current_title or 'Não informado'}")
                    st.markdown(f"**Local:** {rec.location or 'Não informada'}")
                    if rec.linkedin_url:
                        st.markdown(f"[🔗 Ver Perfil no LinkedIn]({rec.linkedin_url})")
                    else:
                        st.caption("⚪ Sem URL do LinkedIn cadastrada")

                with col_r_comp:
                    st.markdown("**Empresa Atual:**")
                    if rec.company_verified:
                        st.markdown(f"✅ **{rec.current_company}** *(confirmada)*")
                    else:
                        st.markdown(
                            f"⏳ **{rec.current_company or 'Pendente'}** *(vínculo a confirmar)*"
                        )
                    if rec.recruitment_focus:
                        st.markdown(f"**Foco:** {', '.join(rec.recruitment_focus)}")
                    if rec.notes:
                        st.caption(f"Notas: {rec.notes}")

                with col_r_actions:
                    btn_draft_key = f"draft_btn_{rec.id}"
                    if st.button("✍️ Gerar Rascunho", key=btn_draft_key, width="stretch"):
                        with st.spinner(f"Gerando rascunho para {rec.name}..."):
                            generate_message_draft(
                                config=cfg,
                                recruiter_id=rec.id,
                                refresh=True,
                            )
                            st.toast(f"Rascunho criado para {rec.name}!")
                            st.rerun()

                    btn_res_key = f"research_btn_{rec.id}"
                    if st.button("🔍 Pesquisar LinkedIn", key=btn_res_key, width="stretch"):
                        with st.spinner(f"Pesquisando {rec.name} via Playwright..."):
                            try:
                                updated_list = asyncio.run(
                                    research_recruiters(cfg, recruiter_id=rec.id)
                                )
                                if updated_list:
                                    u = updated_list[0]
                                    st.success(
                                        f"Recrutador {u.name} atualizado! Empresa: {u.current_company}"  # noqa: E501
                                    )  # noqa: E501
                                    st.rerun()
                                else:
                                    st.warning("Pesquisa concluída sem alterações.")
                            except Exception as e:
                                st.error(f"Erro na pesquisa: {e}")

    with tab_research:
        st.subheader("Pesquisar Recrutadores no LinkedIn (Playwright)")
        st.info(
            "Pesquisa perfil dos recrutadores para identificar e confirmar a empresa atual, "
            "cargo e foco de recrutamento. Requer sessão autenticada em .playwright-profile/."
        )

        rec_options = ["Todos os Recrutadores"] + [f"{r.name} ({r.id})" for r in recruiters]
        selected_rec_target = st.selectbox(
            "Selecione o Recrutador:", rec_options, key="res_rec_select"
        )

        if st.button("🚀 Iniciar Pesquisa no LinkedIn", key="btn_start_res_rec", width="stretch"):
            with st.spinner("Executando automação Playwright para pesquisar perfil(is)..."):
                try:
                    if selected_rec_target == "Todos os Recrutadores":
                        results = asyncio.run(research_recruiters(cfg, research_all=True))
                        st.success(f"{len(results)} recrutador(es) pesquisado(s) e atualizado(s)!")
                    else:
                        m = re.search(r"\((rec-[^)]+)\)", selected_rec_target)
                        target_id = m.group(1) if m else selected_rec_target
                        results = asyncio.run(research_recruiters(cfg, recruiter_id=target_id))
                        st.success(f"Recrutador {selected_rec_target} pesquisado com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao pesquisar recrutador: {e}")

    with tab_edit:
        st.subheader("Atualizar Dados e URL do Recrutador")
        st.caption(
            "Permite atualizar manualmente a URL do LinkedIn ou confirmar vínculo de empresa."
        )

        if not recruiters:
            st.info("Nenhum recrutador disponível para edição.")
        else:
            rec_labels = [f"{r.name} ({r.id})" for r in recruiters]
            selected_rec_label = st.selectbox("Recrutador:", rec_labels, key="edit_rec_select")
            m = re.search(r"\((rec-[^)]+)\)", selected_rec_label)
            sel_id = m.group(1) if m else recruiters[0].id
            sel_rec = storage.get_recruiter(sel_id)

            if sel_rec:
                with st.form("edit_recruiter_form"):
                    e_url = st.text_input(
                        "URL do Perfil no LinkedIn (set-url):", value=sel_rec.linkedin_url or ""
                    )
                    e_comp = st.text_input("Empresa Atual:", value=sel_rec.current_company)
                    e_verified = st.checkbox(
                        "Vínculo com Empresa Confirmado?", value=sel_rec.company_verified
                    )
                    e_title = st.text_input("Título / Cargo Atual:", value=sel_rec.current_title)
                    e_loc = st.text_input("Localização:", value=sel_rec.location)
                    e_notes = st.text_area("Observações / Contexto:", value=sel_rec.notes or "")

                    btn_save_edit = st.form_submit_button("💾 Salvar Atualizações")
                    if btn_save_edit:
                        try:
                            manually_update_recruiter(
                                config=cfg,
                                recruiter_id=sel_rec.id,
                                company_name=e_comp.strip() if e_comp.strip() else None,
                                verified=e_verified,
                                linkedin_url=e_url.strip() if e_url.strip() else None,
                                title=e_title.strip() if e_title.strip() else None,
                                location=e_loc.strip() if e_loc.strip() else None,
                                notes=e_notes.strip() if e_notes.strip() else None,
                            )
                            st.success(f"Dados de {sel_rec.name} atualizados com sucesso!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao atualizar recrutador: {e}")

    with tab_add:
        st.subheader("Cadastrar Novo Recrutador Manualmente")
        with st.form("new_recruiter_form"):
            nr_name = st.text_input("Nome Completo *")
            nr_title = st.text_input("Título / Cargo no LinkedIn")
            nr_comp = st.text_input("Empresa Atual (ou deixe vazio se a confirmar)")
            nr_loc = st.text_input("Localização", value="Porto Alegre, RS")
            nr_url = st.text_input("URL do Perfil no LinkedIn")
            nr_focus = st.text_input("Foco de Recrutamento (separado por vírgula)")
            sub_rec = st.form_submit_button("Salvar Recrutador")
            if sub_rec:
                if not nr_name.strip():
                    st.error("O nome do recrutador é obrigatório.")
                else:
                    slug = re.sub(r"[^a-z0-9]+", "-", nr_name.strip().casefold()).strip("-")
                    rec_id = f"rec-{slug}"
                    focus_list = [f.strip() for f in nr_focus.split(",") if f.strip()]
                    new_rec = Recruiter(
                        id=rec_id,
                        name=nr_name.strip(),
                        linkedin_url=nr_url.strip() if nr_url.strip() else None,
                        current_title=nr_title.strip() or "Recrutamento e Seleção",
                        current_company=nr_comp.strip() or "Pendente",
                        company_verified=bool(nr_comp.strip()),
                        location=nr_loc.strip() or "a confirmar",
                        recruitment_focus=focus_list,
                    )
                    storage.upsert_recruiter(new_rec)
                    st.success(f"Recrutador '{new_rec.name}' cadastrado!")
                    st.rerun()


def render_companies_tab(cfg: AppConfig, storage: JsonStorage) -> None:
    """Aba de empresas mapeadas."""
    st.markdown('<div class="main-header">🏢 Empresas Mapeadas</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Bases corporativas mapeadas a partir das vagas '
        "e recrutadores prospecionados.</div>",
        unsafe_allow_html=True,
    )

    companies = storage.list_companies()

    tab_comp_list, tab_comp_research, tab_comp_add = st.tabs(
        [
            "🏢 Empresas Mapeadas",
            "🔍 Pesquisar no LinkedIn (Playwright)",
            "➕ Cadastrar Empresa Manualmente",
        ]
    )

    with tab_comp_list:
        st.write(f"Total de empresas cadastradas: **{len(companies)}**")
        for comp in companies:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2.5, 2, 2, 1.5])
                with c1:
                    st.markdown(f"### {comp.name}")
                    st.markdown(f"**Setor:** {comp.industry or 'a confirmar'}")
                    if comp.work_model and comp.work_model != "a confirmar":
                        st.markdown(f"**Modelo de Trabalho:** {comp.work_model}")
                with c2:
                    st.markdown(f"**Sede:** {comp.location or 'a confirmar'}")
                    if comp.website:
                        st.markdown(f"[🌐 Site Oficial]({comp.website})")
                with c3:
                    if comp.linkedin_url:
                        st.markdown(f"[🔗 Página no LinkedIn]({comp.linkedin_url})")
                    else:
                        st.caption("⚪ Sem página no LinkedIn cadastrada")
                    if comp.verified_at:
                        st.caption(f"Verificado em: {comp.verified_at[:10]}")
                with c4:
                    btn_c_res_key = f"comp_res_btn_{comp.id}"
                    if st.button("🔍 Pesquisar", key=btn_c_res_key, width="stretch"):
                        with st.spinner(f"Pesquisando dados de {comp.name}..."):
                            try:
                                res = asyncio.run(research_companies(cfg, company_id=comp.id))
                                if res:
                                    st.success(f"Empresa '{comp.name}' verificada com sucesso!")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao pesquisar empresa: {e}")

    with tab_comp_research:
        st.subheader("Pesquisar Empresas no LinkedIn (Playwright)")
        st.info(
            "Pesquisa a página institucional da empresa no LinkedIn para extrair setor, sede, "
            "website e descrição oficial. Requer sessão autenticada em .playwright-profile/."
        )

        comp_options = ["Todas as Empresas"] + [f"{c.name} ({c.id})" for c in companies]
        selected_comp_target = st.selectbox(
            "Selecione a Empresa:", comp_options, key="res_comp_select"
        )

        if st.button("🚀 Iniciar Pesquisa de Empresas", key="btn_start_res_comp", width="stretch"):
            with st.spinner(
                "Executando automação Playwright para pesquisar página(s) de empresa..."
            ):
                try:
                    if selected_comp_target == "Todas as Empresas":
                        results = asyncio.run(research_companies(cfg, research_all=True))
                        st.success(f"{len(results)} empresa(s) pesquisada(s) e atualizada(s)!")
                    else:
                        m = re.search(r"\(([^)]+)\)$", selected_comp_target)
                        target_id = m.group(1) if m else selected_comp_target
                        results = asyncio.run(research_companies(cfg, company_id=target_id))
                        st.success(f"Empresa {selected_comp_target} pesquisada com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao pesquisar empresa: {e}")

    with tab_comp_add:
        st.subheader("Cadastrar Empresa Manualmente")
        with st.form("new_company_form"):
            nc_name = st.text_input("Nome da Empresa *")
            nc_industry = st.text_input("Setor / Indústria", value="Tecnologia da Informação")
            nc_loc = st.text_input("Sede / Localização", value="Porto Alegre, RS")
            nc_web = st.text_input("Website Oficial (URL)")
            nc_li = st.text_input("URL da Página no LinkedIn (URL)")
            nc_model = st.selectbox(
                "Modelo de Trabalho", ["Híbrido", "Remoto", "Presencial", "a confirmar"]
            )
            nc_desc = st.text_area("Descrição Institucional")
            sub_comp = st.form_submit_button("Salvar Empresa")

            if sub_comp:
                if not nc_name.strip():
                    st.error("O nome da empresa é obrigatório.")
                else:
                    slug = re.sub(r"[^a-z0-9]+", "-", nc_name.strip().casefold()).strip("-")
                    comp_id = f"comp-{slug}"
                    new_comp = Company(
                        id=comp_id,
                        name=nc_name.strip(),
                        website=nc_web.strip() if nc_web.strip() else None,
                        linkedin_url=nc_li.strip() if nc_li.strip() else None,
                        industry=nc_industry.strip() or "a confirmar",
                        location=nc_loc.strip() or "a confirmar",
                        work_model=nc_model,
                        company_description=nc_desc.strip(),
                    )
                    storage.upsert_company(new_comp)
                    st.success(f"Empresa '{new_comp.name}' cadastrada com sucesso!")
                    st.rerun()


def render_messages_tab(cfg: AppConfig, storage: JsonStorage) -> None:
    """Aba de revisão humana e controle de rascunhos de abordagem."""
    st.markdown(
        '<div class="main-header">✍️ Rascunhos de Mensagens (Human-in-the-Loop)</div>',
        unsafe_allow_html=True,
    )

    st.warning(
        "🛡️ **CONTROLE HUMANO OBRIGATÓRIO (Human-in-the-Loop):**\n\n"
        "Esta ferramenta **NUNCA** envia mensagens ou convites automaticamente no LinkedIn.\n"
        "Revise o rascunho sugerido, ajuste o texto conforme desejar e faça o envio manualmente "
        "a partir do seu próprio perfil autenticado no LinkedIn."
    )

    messages = storage.list_messages()
    recruiters = storage.list_recruiters()
    jobs = storage.list_jobs()
    recruiter_map = {r.id: r for r in recruiters}

    tab_review, tab_generate = st.tabs(
        [
            "📝 Revisão e Edição de Rascunhos",
            "✨ Gerar Novos Rascunhos",
        ]
    )

    with tab_generate:
        st.subheader("Gerar Novos Rascunhos de Mensagem")
        st.caption(
            "Crie abordagens personalizadas baseadas no currículo e contexto do recrutador/vaga."
        )

        col_g1, col_g2 = st.columns(2)
        rec_choices = ["Todos os Recrutadores"] + [f"{r.name} ({r.id})" for r in recruiters]
        sel_rec_target = col_g1.selectbox(
            "Destinatário (Recrutador):", rec_choices, key="gen_msg_rec"
        )

        job_choices = ["Nenhuma vaga vinculada (Abordagem Espontânea/Geral)"] + [
            f"{j.title} — {j.company} ({j.id})" for j in jobs
        ]
        sel_job_target = col_g2.selectbox(
            "Vincular a Vaga Específica (Opcional):", job_choices, key="gen_msg_job"
        )

        col_opt1, col_opt2, col_opt3 = st.columns([1.5, 1.5, 2])
        gen_refresh = col_opt1.checkbox(
            "🔄 Forçar regeração (--refresh)", value=True, key="gen_msg_refresh"
        )
        gen_offline = col_opt2.checkbox(
            "⚡ Forçar offline determinístico (--offline)", value=False, key="gen_msg_offline"
        )
        gen_provider_choice = col_opt3.selectbox(
            "Provedor LLM:",
            ["Padrão (.env)", "Ollama (Local)", "Gemini (Nuvem)", "Offline (Regras Locais)"],
            key="gen_msg_provider",
        )

        if st.button("✍️ Gerar Rascunho(s) Agora", key="btn_execute_gen_msg", width="stretch"):
            provider_override = None
            if gen_provider_choice == "Ollama (Local)":
                provider_override = "ollama"
            elif gen_provider_choice == "Gemini (Nuvem)":
                provider_override = "gemini"
            elif gen_provider_choice == "Offline (Regras Locais)":
                provider_override = "offline"

            chosen_provider = (
                get_llm_provider(cfg, provider_override=provider_override)
                if provider_override
                else None
            )

            target_job_id = None
            if sel_job_target != "Nenhuma vaga vinculada (Abordagem Espontânea/Geral)":
                m_job = re.search(r"\(([^)]+)\)$", sel_job_target)
                if m_job:
                    target_job_id = m_job.group(1)

            with st.spinner("Gerando rascunho(s) estruturado(s)..."):
                try:
                    if sel_rec_target == "Todos os Recrutadores":
                        created = generate_all_drafts(
                            cfg,
                            refresh=gen_refresh,
                            force_offline=gen_offline,
                            llm_provider=chosen_provider,
                        )
                        st.success(f"{len(created)} rascunho(s) gerado(s) com sucesso!")
                    else:
                        m_rec = re.search(r"\((rec-[^)]+)\)", sel_rec_target)
                        target_rec_id = m_rec.group(1) if m_rec else recruiters[0].id
                        generate_message_draft(
                            config=cfg,
                            recruiter_id=target_rec_id,
                            job_id=target_job_id,
                            refresh=gen_refresh,
                            force_offline=gen_offline,
                            llm_provider=chosen_provider,
                        )
                        st.success(f"Rascunho gerado para {sel_rec_target}!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao gerar rascunho: {e}")

    with tab_review:
        if not messages:
            st.info(
                "Nenhum rascunho gerado ainda. Use a aba 'Gerar Novos Rascunhos' ao lado "
                "ou as ações rápidas no Dashboard."
            )
        else:
            options = []
            msg_dict = {}
            for m in messages:
                rec = recruiter_map.get(m.recruiter_id)
                label = (
                    f"{rec.name if rec else m.recruiter_id} — "
                    f"[{m.review_status.value}] "
                    f"({'Enviada' if m.sent_by_user else 'Não enviada'})"
                )
                options.append(label)
                msg_dict[label] = m

            selected_label = st.selectbox(
                "Selecione o Rascunho para Revisar:", options, key="rev_msg_select"
            )
            selected_msg = msg_dict[selected_label]
            recruiter = recruiter_map.get(selected_msg.recruiter_id)

            st.divider()

            col_meta, col_actions = st.columns([2, 1])

            with col_meta:
                target_name = recruiter.name if recruiter else selected_msg.recruiter_id
                st.markdown(f"### Destinatário: **{target_name}**")
                st.markdown(f"**Contexto:** {selected_msg.context}")
                st.markdown(f"**Status da Revisão:** `{selected_msg.review_status.value}`")
                st.markdown(
                    f"**Enviada Manualmente pelo Usuário:** "
                    f"{'✅ Sim' if selected_msg.sent_by_user else '❌ Ainda não'}"
                )
                if selected_msg.sent_at:
                    st.markdown(f"**Data do Envio Manual:** `{selected_msg.sent_at[:10]}`")

            with col_actions:
                st.markdown("**Ações de Revisão Humana:**")
                if st.button("✅ Aprovar Rascunho", key="btn_appr_msg", width="stretch"):
                    review_message(cfg, selected_msg.id, status=ReviewStatus.APPROVED)
                    st.success("Rascunho marcado como Aprovado!")
                    st.rerun()

                if st.button("❌ Descartar Rascunho", key="btn_disc_msg", width="stretch"):
                    review_message(cfg, selected_msg.id, status=ReviewStatus.DISCARDED)
                    st.warning("Rascunho marcado como Descartado.")
                    st.rerun()

                if st.button(
                    "🚀 Marcar como Enviado no LinkedIn", key="btn_sent_msg", width="stretch"
                ):
                    review_message(cfg, selected_msg.id, mark_sent=True)
                    st.success("Registrado como enviado manualmente pelo usuário!")
                    st.rerun()

            st.markdown("#### 📝 Editor do Texto da Mensagem (Copie e Personalize)")
            edited_text = st.text_area(
                "Edite o texto antes de enviar manualmente:",
                value=selected_msg.message_text,
                height=180,
                key="rev_msg_textarea",
            )

            if st.button("💾 Salvar Alterações no Texto", key="btn_save_msg_text"):
                review_message(cfg, selected_msg.id, edited_text=edited_text)
                st.success("Texto atualizado e salvo com sucesso!")
                st.rerun()

            st.divider()

            st.markdown("#### ✅ Checklist de Conferência")
            st.checkbox(
                "O tom da mensagem reflete meu estilo pessoal de comunicação.",
                value=True,
                key="chk_tone",
            )
            st.checkbox(
                "As competências citadas representam com fidelidade a experiência comprovada.",
                value=True,
                key="chk_comp",
            )
            st.checkbox(
                "Se foi citada empresa, o vínculo do recrutador foi conferido no perfil dele.",
                value=True,
                key="chk_link",
            )
            st.checkbox(
                "A mensagem foi copiada e colada manualmente no LinkedIn.",
                value=selected_msg.sent_by_user,
                key="chk_pasted",
            )


def render_report_tab(cfg: AppConfig, storage: JsonStorage) -> None:
    """Aba de visualização do relatório executivo consolidado."""
    st.markdown('<div class="main-header">📑 Relatório Consolidado</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Documento executivo completo de prospecção, '
        "vagas ranqueadas e abordagem.</div>",
        unsafe_allow_html=True,
    )

    report_file = cfg.output_dir / "relatorio_consolidado.md"

    col_btn, col_down = st.columns([2, 1])
    with col_btn:
        if st.button("🔄 Atualizar Relatório com Dados Mais Recentes", width="stretch"):
            with st.spinner("Gerando relatório..."):
                generate_consolidated_report(cfg)
                st.success("Relatório consolidado atualizado!")
                st.rerun()

    if report_file.exists():
        content = report_file.read_text(encoding="utf-8")
        with col_down:
            st.download_button(
                label="⬇️ Baixar Relatório (.md)",
                data=content,
                file_name="relatorio_consolidado.md",
                mime="text/markdown",
                width="stretch",
            )
        st.divider()
        st.markdown(content)
    else:
        st.info("O relatório consolidado ainda não foi gerado.")
        if st.button("Gerar Agora"):
            generate_consolidated_report(cfg)
            st.rerun()


def render_settings_tab(cfg: AppConfig, storage: JsonStorage) -> None:
    """Aba de sessão do Playwright, diagnóstico do ambiente, teste de LLM e perfil."""
    st.markdown('<div class="main-header">⚙️ Sessão & Diagnóstico</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Gerenciamento da sessão local do Playwright, '
        "verificação de integridade, testes de LLM e logs.</div>",
        unsafe_allow_html=True,
    )

    t1, t2, t3, t4, t5 = st.tabs(
        [
            "🌐 Sessão LinkedIn",
            "🩺 Diagnóstico (Doctor)",
            "🤖 Teste de LLM",
            "👤 Perfil do Candidato",
            "📄 Logs",
        ]
    )

    with t1:
        st.subheader("Sessão Persistente do Playwright")
        st.markdown(f"**Diretório do Perfil:** `{cfg.user_data_dir}`")
        has_session = has_persistent_session(cfg.user_data_dir)

        if has_session:
            st.success(
                "🟢 Perfil persistente detectado com cookies de sessão do LinkedIn! "
                "As pesquisas e extrações utilizarão esta sessão local com segurança."
            )
        else:
            st.warning(
                "⚪ Nenhuma sessão ativa detectada em `.playwright-profile/`. "
                "Clique no botão abaixo para iniciar o login manual assistido."
            )

        st.info(
            "💡 O comando abaixo abre uma janela do Chromium local na sua máquina. "
            "Você realiza o login e eventual 2FA normalmente. Uma vez no feed, "
            "a sessão é salva permanentemente para as próximas consultas."
        )

        if st.button("🚀 Iniciar Login Manual Assistido no Navegador", key="btn_login_settings"):
            with st.spinner("Abrindo janela do navegador Chromium local..."):
                try:
                    success = asyncio.run(interactive_login(cfg))
                    if success:
                        st.success("Login detectado com sucesso!")
                        st.rerun()
                    else:
                        st.warning("O login não foi concluído antes do fechamento do navegador.")
                except Exception as e:
                    st.error(f"Erro no login manual: {e}")

    with t2:
        st.subheader("🩺 Diagnóstico do Ambiente (Doctor)")
        st.write("Verificação completa de dependências, integridade de arquivos e conectividade:")

        if st.button("🩺 Executar Diagnóstico Completo", width="stretch", key="btn_run_doctor"):
            checks = collect_doctor_checks(cfg)
            ok_count = sum(1 for _, ok, _ in checks if ok)
            fail_count = len(checks) - ok_count

            c_doc1, c_doc2 = st.columns(2)
            c_doc1.metric("Verificações Aprovadas", f"{ok_count}/{len(checks)}")
            c_doc2.metric("Avisos / Pendências", fail_count)

            st.divider()
            for label, ok, detail in checks:
                icon = "✅" if ok else "⚠️"
                with st.container(border=True):
                    col_ico, col_det = st.columns([0.5, 9.5])
                    col_ico.markdown(f"### {icon}")
                    with col_det:
                        st.markdown(f"**{label}**")
                        st.caption(detail)

    with t3:
        st.subheader("🤖 Teste de LLM e Benchmarking em Tempo Real")
        st.markdown(f"**Provedor Padrão Configurado (.env):** `{cfg.llm_provider}`")
        if cfg.llm_provider == "ollama":
            st.markdown(
                f"**Modelo Ollama:** `{cfg.ollama_model}` | **Endpoint:** `{cfg.ollama_base_url}`"
            )
        elif cfg.llm_provider == "gemini":
            st.markdown(f"**Modelo Gemini:** `{cfg.gemini_model}`")

        llm_test_choice = st.selectbox(
            "Provedor a ser testado:",
            [
                "Provedor Atual (.env)",
                "Ollama (Local)",
                "Gemini (Nuvem)",
                "Offline (Determinístico)",
            ],
            key="settings_llm_choice",
        )

        if st.button(
            "🧪 Testar Resposta do LLM em Tempo Real", width="stretch", key="btn_test_llm_ping"
        ):
            override = None
            if llm_test_choice == "Ollama (Local)":
                override = "ollama"
            elif llm_test_choice == "Gemini (Nuvem)":
                override = "gemini"
            elif llm_test_choice == "Offline (Determinístico)":
                override = "offline"

            target_provider = (
                get_llm_provider(cfg, provider_override=override)
                if override
                else get_llm_provider(cfg)
            )

            st.write(f"Iniciando chamada para: `{target_provider.name}`...")
            if not target_provider.is_available():
                st.error(f"❌ O provedor `{target_provider.name}` não está disponível ou offline.")
            else:

                class PingTestSchema(BaseModel):
                    status: str = Field(description="Deve ser 'OK'")
                    model_response: str = Field(
                        description="Uma mensagem curta de validação em português"
                    )
                    latency_evaluation: str = Field(
                        description="Avaliação breve sobre velocidade/resposta"
                    )

                prompt = (
                    "Responda a este teste de conectividade estruturada em JSON.\n"
                    "status: OK\n"
                    "model_response: Mensagem confirmando que o modelo está ativo e operacional.\n"
                    "latency_evaluation: 'Resposta em tempo hábil para inferência local/remota.'"
                )

                t0 = time.perf_counter()
                with st.spinner("Aguardando inferência do modelo..."):
                    res = target_provider.generate_structured(prompt, PingTestSchema)
                elapsed = time.perf_counter() - t0

                if res:
                    st.success(
                        f"✅ Sucesso! Inferência concluída em **{elapsed:.2f}s** via `{target_provider.name}`."  # noqa: E501
                    )
                    with st.container(border=True):
                        st.json(res.model_dump())
                else:
                    st.warning(
                        f"O provedor `{target_provider.name}` não retornou schema válido em {elapsed:.2f}s."  # noqa: E501
                    )

    with t4:
        st.subheader("👤 Perfil do Candidato Ativo (Profile Management)")
        safe_load_candidate_profile(cfg)

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown(f"**Arquivo de Perfil:** `{cfg.candidate_profile_file.name}`")
            st.markdown(
                f"Status: {'🟢 Presente' if cfg.candidate_profile_file.exists() else '⚪ Não encontrado'}"  # noqa: E501
            )

            st.markdown(
                f"**Currículo em PDF:** `{cfg.curriculum_path.name if cfg.curriculum_path else 'Não informado'}`"  # noqa: E501
            )
            st.markdown(
                f"Status: {'🟢 Presente' if cfg.curriculum_path and cfg.curriculum_path.exists() else '⚪ Não encontrado'}"  # noqa: E501
            )

        with col_p2:
            st.markdown(f"**Informações Adicionais:** `{cfg.candidate_additional_info_file.name}`")
            st.markdown(
                f"Status: {'🟢 Presente' if cfg.candidate_additional_info_file.exists() else '⚪ Não encontrado'}"  # noqa: E501
            )

        st.divider()

        col_pb1, col_pb2 = st.columns(2)
        with col_pb1:
            if st.button(
                "🔄 Reconstruir Perfil (profile build)",
                width="stretch",
                key="btn_build_profile_settings",
            ):
                with st.spinner("Construindo perfil a partir do PDF e MD..."):
                    try:
                        p, recs = build_profile_and_recruiters_from_cv_and_md(
                            pdf_path=cfg.curriculum_path,
                            md_path=cfg.candidate_additional_info_file
                            if cfg.candidate_additional_info_file.exists()
                            else None,
                            config=cfg,
                        )
                        st.success(
                            f"Perfil reconstruído com sucesso! {len(recs)} recrutadores extraídos."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao reconstruir perfil: {e}")

        with col_pb2:
            if st.button(
                "📄 Inicializar Templates (profile init)",
                width="stretch",
                key="btn_init_profile_settings",
            ):
                try:
                    if (
                        not cfg.candidate_profile_file.exists()
                        and cfg.candidate_profile_template_file.exists()
                    ):
                        cfg.candidate_profile_file.write_text(
                            cfg.candidate_profile_template_file.read_text(encoding="utf-8"),
                            encoding="utf-8",
                        )
                    if (
                        not cfg.candidate_additional_info_file.exists()
                        and cfg.candidate_additional_info_template_file.exists()
                    ):
                        cfg.candidate_additional_info_file.write_text(
                            cfg.candidate_additional_info_template_file.read_text(encoding="utf-8"),
                            encoding="utf-8",
                        )
                    st.success("Arquivos template inicializados!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao inicializar perfil: {e}")

    with t5:
        st.subheader("Visualizador de Logs")
        log_file = cfg.logs_dir / "linkedin_researcher.log"
        if log_file.exists():
            with st.expander("📄 Logs da Aplicação (linkedin_researcher.log)", expanded=True):
                lines = log_file.read_text(encoding="utf-8").splitlines()
                recent = "\n".join(lines[-40:])
                st.code(recent, language="text")

        web_log_file = cfg.logs_dir / "web_server.log"
        if web_log_file.exists():
            with st.expander("🌐 Logs do Servidor Web (web_server.log)"):
                web_lines = web_log_file.read_text(encoding="utf-8").splitlines()
                recent_web = "\n".join(web_lines[-60:])
                st.code(recent_web, language="text")


def main() -> None:
    """Ponto de entrada da aplicação Streamlit."""
    cfg, storage = get_app_context()
    selected_page = render_sidebar(cfg, storage)

    if selected_page == "📊 Visão Geral":
        render_dashboard(cfg, storage)
    elif selected_page == "🎯 Vagas & Matching":
        render_jobs_tab(cfg, storage)
    elif selected_page == "👥 Recrutadores":
        render_recruiters_tab(cfg, storage)
    elif selected_page == "🏢 Empresas":
        render_companies_tab(cfg, storage)
    elif selected_page == "✍️ Rascunhos de Mensagens":
        render_messages_tab(cfg, storage)
    elif selected_page == "📑 Relatório Consolidado":
        render_report_tab(cfg, storage)
    elif selected_page == "⚙️ Sessão & Diagnóstico":
        render_settings_tab(cfg, storage)


if __name__ == "__main__":
    main()
