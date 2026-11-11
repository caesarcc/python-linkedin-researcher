"""Modelos de domínio tipados e validados (Pydantic v2) — Etapa 2.

Define as entidades principais do projeto:
- Recruiter (Recrutador)
- Company (Empresa)
- Job (Vaga)
- SuggestedMessage (Mensagem sugerida para revisão humana)
- ExperienceEntry e CandidateProfile (Perfil estruturado do currículo do candidato)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_URL_SCHEMES = ("http://", "https://", "file://")


def _validate_optional_url(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not value.startswith(ALLOWED_URL_SCHEMES):
        raise ValueError(f"URL inválida '{value}'. Deve iniciar com http://, https:// ou file://.")
    return value


class MatchLevel(StrEnum):
    """Classificação explicável de aderência da vaga ao perfil do candidato."""

    HIGH = "Alta aderência"
    MEDIUM = "Média aderência"
    LOW = "Baixa aderência"
    NOT_EVALUATED = "Não avaliada"


class JobStatus(StrEnum):
    """Ciclo de vida da vaga pesquisada."""

    IDENTIFIED = "identificada"
    ANALYZED = "analisada"
    UNDER_REVIEW = "em_revisao"
    DISCARDED = "descartada"
    APPLIED_MANUALLY = "candidatada_manualmente"


class ReviewStatus(StrEnum):
    """Status de revisão humana da mensagem sugerida."""

    PENDING_REVIEW = "pendente_revisao"
    APPROVED = "aprovada"
    EDITED = "editada"
    DISCARDED = "descartada"


class ReplyStatus(StrEnum):
    """Status de acompanhamento manual de envio e resposta."""

    NOT_SENT = "sem_envio"
    WAITING_REPLY = "aguardando_resposta"
    REPLIED = "respondeu"
    NO_REPLY = "sem_resposta"


class Recruiter(BaseModel):
    """Representa um recrutador ou profissional de RH/R&S identificado no LinkedIn."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(..., min_length=1, description="Identificador único do recrutador")
    name: str = Field(..., min_length=2, description="Nome profissional exibido")
    linkedin_url: str | None = Field(default=None, description="URL do perfil no LinkedIn")
    current_title: str = Field(..., min_length=2, description="Título ou resumo exibido")
    current_company: str = Field(
        default="Pendente",
        min_length=1,
        description="Empresa atual ('Pendente' ou 'a confirmar' até verificação)",
    )
    location: str = Field(..., min_length=2, description="Localização profissional exibida")
    recruitment_focus: list[str] = Field(
        default_factory=list,
        description="Áreas, níveis ou tipos de vagas recrutadas observados",
    )
    company_verified: bool = Field(
        default=False,
        description="True somente após confirmação visível e atual do vínculo na sessão",
    )
    profile_checked_at: str | None = Field(
        default=None,
        description="Data/hora ISO-8601 da última consulta ao perfil",
    )
    professional_context: str = Field(
        default="a confirmar",
        description="Contexto profissional observado para personalização",
    )
    common_connections: list[str] = Field(
        default_factory=list,
        description="Conexões em comum relevantes e visíveis",
    )
    notes: str = Field(
        default=(
            "Dados iniciais extraídos de captura de tela; "
            "confirmar vínculo e vagas antes de abordar."
        ),
        description="Observações e distinção entre fatos observados e pendências",
    )
    source_url: str | None = Field(
        default=None,
        description="URL de origem de onde os dados foram extraídos",
    )

    @field_validator("linkedin_url", "source_url")
    @classmethod
    def validate_urls(cls, value: str | None) -> str | None:
        return _validate_optional_url(value)


class Company(BaseModel):
    """Representa uma empresa pesquisada e associada a recrutadores ou vagas."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(..., min_length=1, description="Identificador único da empresa")
    name: str = Field(..., min_length=2, description="Nome da empresa")
    website: str | None = Field(default=None, description="Website oficial da empresa")
    linkedin_url: str | None = Field(default=None, description="URL da página no LinkedIn")
    industry: str = Field(
        default="a confirmar",
        description="Setor/indústria da empresa",
    )
    location: str = Field(
        default="a confirmar",
        description="Sede ou localidade principal",
    )
    work_model: str = Field(
        default="a confirmar",
        description="Modelo de trabalho praticado (remoto, híbrido, presencial)",
    )
    company_description: str = Field(
        default="",
        description="Resumo institucional extraído da página",
    )
    verified_at: str | None = Field(
        default=None,
        description="Data/hora ISO-8601 da verificação",
    )
    source_urls: list[str] = Field(
        default_factory=list,
        description="URLs consultadas para confirmar os dados da empresa",
    )

    @field_validator("website", "linkedin_url")
    @classmethod
    def validate_urls(cls, value: str | None) -> str | None:
        return _validate_optional_url(value)

    @field_validator("source_urls")
    @classmethod
    def validate_source_urls(cls, urls: list[str]) -> list[str]:
        for u in urls:
            _validate_optional_url(u)
        return urls


class Job(BaseModel):
    """Representa uma vaga identificada e sua avaliação de aderência ao perfil do candidato."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(..., min_length=1, description="Identificador único da vaga")
    title: str = Field(..., min_length=2, description="Título da vaga")
    company: str = Field(..., min_length=1, description="Empresa anunciante ou consultoria")
    location: str = Field(
        default="a confirmar",
        description="Localidade da vaga",
    )
    work_model: str = Field(
        default="a confirmar",
        description="Modalidade (Remoto, Híbrido, Presencial ou a confirmar)",
    )
    contract_type: str = Field(
        default="a confirmar",
        description="Tipo de contratação (CLT, PJ, Temporário ou a confirmar)",
    )
    salary_range: str = Field(
        default="Não informado",
        description="Faixa salarial quando divulgada",
    )
    description: str = Field(default="", description="Texto descritivo da vaga")
    requirements: list[str] = Field(
        default_factory=list,
        description="Requisitos identificados na vaga",
    )
    responsibilities: list[str] = Field(
        default_factory=list,
        description="Atividades e responsabilidades previstas",
    )
    application_url: str = Field(
        ..., min_length=5, description="URL da vaga para consulta/aplicação"
    )
    published_at: str | None = Field(
        default=None,
        description="Data ou indicação de publicação da vaga",
    )
    checked_at: str = Field(
        ...,
        min_length=8,
        description="Data/hora ISO-8601 da consulta à vaga",
    )
    match_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Estimativa numérica auxiliar de aderência (0 a 100)",
    )
    match_level: MatchLevel = Field(
        default=MatchLevel.NOT_EVALUATED,
        description="Classificação explicável de aderência (Alta, Média, Baixa, Não avaliada)",
    )
    strengths: list[str] = Field(
        default_factory=list,
        description="Pontos fortes e compatibilidades com o currículo do candidato",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Lacunas, incompatibilidades ou pontos a confirmar com o candidato",
    )
    status: JobStatus = Field(
        default=JobStatus.IDENTIFIED,
        description="Status atual da vaga no fluxo de análise",
    )
    source_urls: list[str] = Field(
        default_factory=list,
        description="Lista de URLs consultadas para a vaga",
    )

    @field_validator("application_url")
    @classmethod
    def validate_app_url(cls, value: str) -> str:
        validated = _validate_optional_url(value)
        if not validated:
            raise ValueError("application_url é obrigatória.")
        return validated

    @field_validator("source_urls")
    @classmethod
    def validate_source_urls(cls, urls: list[str]) -> list[str]:
        for u in urls:
            _validate_optional_url(u)
        return urls

    @model_validator(mode="after")
    def ensure_application_url_in_sources(self) -> Job:
        if self.application_url not in self.source_urls:
            self.source_urls.append(self.application_url)
        return self


class SuggestedMessage(BaseModel):
    """Representa um rascunho de mensagem personalizado para revisão e envio manual."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(..., min_length=1, description="Identificador único da mensagem")
    recruiter_id: str = Field(..., min_length=1, description="ID do recrutador destinatário")
    context: str = Field(
        ..., min_length=2, description="Resumo do contexto usado na personalização"
    )
    message_text: str = Field(..., min_length=10, description="Texto sugerido em primeira pessoa")
    created_at: str = Field(..., min_length=8, description="Data/hora ISO-8601 da geração")
    review_status: ReviewStatus = Field(
        default=ReviewStatus.PENDING_REVIEW,
        description="Status da revisão humana",
    )
    sent_by_user: bool = Field(
        default=False,
        description="Indica se a titular informou ter enviado a mensagem manualmente",
    )
    sent_at: str | None = Field(
        default=None,
        description="Data/hora informada do envio manual pela titular",
    )
    reply_status: ReplyStatus = Field(
        default=ReplyStatus.NOT_SENT,
        description="Status de resposta do recrutador",
    )
    notes: str = Field(default="", description="Anotações da revisão humana")


class ExperienceEntry(BaseModel):
    """Experiência profissional comprovada no currículo em PDF e contextualizada no brief."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company: str
    period_pdf: str
    role_in_pdf: str
    positioning_role: str
    is_current: bool = False
    activities: list[str]


class CandidateProfile(BaseModel):
    """Perfil profissional estruturado de um candidato para análise de aderência e mensagens."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str
    location: str
    linkedin_url: str
    education: str
    contract_availability: list[str]
    has_active_mei: bool
    preferred_work_model: str
    priority_areas: list[str]
    target_levels: list[str]
    target_roles_primary: list[str]
    target_roles_expanded: list[str]
    excluded_roles_and_levels: list[str]
    proven_competencies: list[str]
    behavioral_competencies: list[str]
    office_proficiency: str
    experiences: list[ExperienceEntry]
    pending_confirmations: list[str]
    additional_info: str | None = Field(
        default=None,
        description="Diretrizes e informações qualitativas adicionais complementares",
    )
