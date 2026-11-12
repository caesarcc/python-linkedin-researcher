"""Interface Web Interativa com Streamlit para o LinkedIn Researcher & Career Assistant."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

from linkedin_researcher.analysis.curriculum_profile import (
    build_profile_and_recruiters_from_cv_and_md,
    load_candidate_profile,
)
from linkedin_researcher.analysis.job_matching import match_all_jobs, match_job
from linkedin_researcher.analysis.ranking import rank_jobs
from linkedin_researcher.browser.session_manager import interactive_login
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
    JobStatus,
    MatchLevel,
    Recruiter,
    ReviewStatus,
)
from linkedin_researcher.research.job_research import (
    register_job_by_url,
    register_job_manually,
    research_jobs,
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
        ollama_status = "🟢 Conectado" if provider.is_available() else "⚪ Offline / Execute 'ollama pull'"
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

        if st.button("📑 Gerar / Atualizar Relatório Consolidado", width="stretch"):
            with st.spinner("Compilando relatório consolidado..."):
                report_path = generate_consolidated_report(cfg)
                st.success(f"Relatório gerado em `{report_path}`!")

        if st.button("🎯 Avaliar Aderência de Todas as Vagas", width="stretch"):
            with st.spinner("Executando análise de aderência (7 dimensões)..."):
                updated = match_all_jobs(cfg, refresh=False, force_offline=False)
                st.success(f"{len(updated)} vagas avaliadas com sucesso!")
                st.rerun()

        if st.button("✍️ Gerar Rascunhos para Todos os Recrutadores", width="stretch"):
            with st.spinner("Gerando rascunhos de abordagem para revisão humana..."):
                drafts = generate_all_drafts(cfg, refresh=False, force_offline=False)
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

    recruiters = storage.list_recruiters()
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

            with col_r_actions:
                btn_draft_key = f"draft_btn_{rec.id}"
                if st.button("✍️ Gerar Rascunho", key=btn_draft_key, width="stretch"):
                    with st.spinner("Gerando rascunho..."):
                        generate_message_draft(
                            config=cfg,
                            recruiter_id=rec.id,
                            refresh=True,
                        )
                        st.toast(f"Rascunho criado para {rec.name}!")
                        st.rerun()

    st.divider()
    with st.expander("➕ Cadastrar Novo Recrutador Manualmente"):
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
    st.write(f"Total de empresas cadastradas: **{len(companies)}**")

    for comp in companies:
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 2, 2])
            with c1:
                st.markdown(f"### {comp.name}")
                st.markdown(f"**Setor:** {comp.industry or 'a confirmar'}")
            with c2:
                st.markdown(f"**Sede:** {comp.location or 'a confirmar'}")
                if comp.website:
                    st.markdown(f"[🌐 Site Oficial]({comp.website})")
            with c3:
                if comp.linkedin_url:
                    st.markdown(f"[🔗 Página no LinkedIn]({comp.linkedin_url})")


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
    recruiter_map = {r.id: r for r in recruiters}

    if not messages:
        st.info(
            "Nenhum rascunho gerado ainda. Use o botão abaixo ou gere rascunhos "
            "a partir da aba de Recrutadores."
        )
        if st.button("Gerar Rascunhos para Todos os Recrutadores"):
            with st.spinner("Gerando rascunhos..."):
                generate_all_drafts(cfg)
                st.rerun()
        return

    # Seletor de mensagem
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

    selected_label = st.selectbox("Selecione o Rascunho para Revisar:", options)
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
        if st.button("✅ Aprovar Rascunho", width="stretch"):
            review_message(cfg, selected_msg.id, status=ReviewStatus.APPROVED)
            st.success("Rascunho marcado como Aprovado!")
            st.rerun()

        if st.button("❌ Descartar Rascunho", width="stretch"):
            review_message(cfg, selected_msg.id, status=ReviewStatus.DISCARDED)
            st.warning("Rascunho marcado como Descartado.")
            st.rerun()

        if st.button("🚀 Marcar como Enviado no LinkedIn", width="stretch"):
            review_message(cfg, selected_msg.id, mark_sent=True)
            st.success("Registrado como enviado manualmente pelo usuário!")
            st.rerun()

    st.markdown("#### 📝 Editor do Texto da Mensagem (Copie e Personalize)")
    edited_text = st.text_area(
        "Edite o texto antes de enviar manualmente:",
        value=selected_msg.message_text,
        height=180,
    )

    if st.button("💾 Salvar Alterações no Texto"):
        review_message(cfg, selected_msg.id, edited_text=edited_text)
        st.success("Texto atualizado e salvo com sucesso!")
        st.rerun()

    st.divider()

    st.markdown("#### ✅ Checklist de Conferência")
    st.checkbox("O tom da mensagem reflete meu estilo pessoal de comunicação.", value=True)
    st.checkbox(
        "As competências citadas representam com fidelidade a experiência comprovada.",
        value=True,
    )
    st.checkbox(
        "Se foi citada empresa, o vínculo do recrutador foi conferido no perfil dele.",
        value=True,
    )
    st.checkbox(
        "A mensagem foi copiada e colada manualmente no LinkedIn.",
        value=selected_msg.sent_by_user,
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
    """Aba de sessão do Playwright, diagnóstico do ambiente e logs."""
    st.markdown('<div class="main-header">⚙️ Sessão & Diagnóstico</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Gerenciamento da sessão local do Playwright, '
        "verificação de integridade e logs.</div>",
        unsafe_allow_html=True,
    )

    t1, t2 = st.tabs(["🌐 Sessão LinkedIn & Autenticação", "🩺 Diagnóstico do Ambiente"])

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

        if st.button("🚀 Iniciar Login Manual Assistido no Navegador"):
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
        st.subheader("Verificação do Ambiente")
        st.markdown(f"**Raiz do Projeto:** `{cfg.project_root}`")
        st.markdown(f"**Diretório de Dados:** `{cfg.data_dir}`")
        st.markdown(f"**Currículo em PDF:** `{cfg.curriculum_path}`")
        st.markdown(f"**Diretório de Saída:** `{cfg.output_dir}`")

        # Visualizadores de log
        log_file = cfg.logs_dir / "linkedin_researcher.log"
        if log_file.exists():
            with st.expander("📄 Ver Logs Recentes da Aplicação"):
                lines = log_file.read_text(encoding="utf-8").splitlines()
                recent = "\n".join(lines[-40:])
                st.code(recent, language="text")

        web_log_file = cfg.logs_dir / "web_server.log"
        if web_log_file.exists():
            with st.expander("🌐 Ver Logs do Servidor Web (web_server.log)"):
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
