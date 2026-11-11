"""Camada de persistência local em JSON com escrita atômica, validação e deduplicação — Etapa 2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from linkedin_researcher.config import AppConfig
from linkedin_researcher.models import Company, Job, Recruiter, SuggestedMessage

T = TypeVar("T", bound=BaseModel)


def _normalize_text(value: str | None) -> str:
    """Normaliza string para comparação de deduplicação (casefold e espaços simples)."""
    if not value:
        return ""
    return " ".join(value.strip().casefold().split())


def _normalize_url(url: str | None) -> str:
    """Normaliza URL removendo barra final e parâmetros de rastreamento comuns."""
    if not url:
        return ""
    clean = url.strip().split("?")[0].rstrip("/")
    return clean.casefold()


class JsonStorage:
    """Gerencia leitura, gravação atômica, validação Pydantic e deduplicação em arquivos JSON."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.data_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read_models(file_path: Path, model_cls: type[T]) -> list[T]:
        if not file_path.exists():
            return []
        raw_text = file_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return []
        raw_list = json.loads(raw_text)
        if not isinstance(raw_list, list):
            raise ValueError(f"O arquivo {file_path} deve conter uma lista JSON na raiz.")
        return [model_cls.model_validate(item) for item in raw_list]

    @staticmethod
    def _write_models(file_path: Path, items: list[T]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_suffix(f"{file_path.suffix}.tmp")
        payload = [item.model_dump(mode="json") for item in items]
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(file_path)

    # ------------------------------------------------------------------
    # Recrutadores
    # ------------------------------------------------------------------

    def list_recruiters(self) -> list[Recruiter]:
        return self._read_models(self.config.recruiters_file, Recruiter)

    def get_recruiter(self, recruiter_id: str) -> Recruiter | None:
        target = recruiter_id.strip()
        for rec in self.list_recruiters():
            if rec.id == target:
                return rec
        return None

    def upsert_recruiter(self, recruiter: Recruiter) -> Recruiter:
        """Insere ou atualiza um recrutador, evitando duplicidade por id, URL ou (nome, local)."""
        existing = self.list_recruiters()
        norm_url = _normalize_url(recruiter.linkedin_url)
        norm_name = _normalize_text(recruiter.name)
        norm_loc = _normalize_text(recruiter.location)

        match_idx: int | None = None
        for idx, item in enumerate(existing):
            if item.id == recruiter.id:
                match_idx = idx
                break
            if norm_url and _normalize_url(item.linkedin_url) == norm_url:
                match_idx = idx
                break
            if (
                _normalize_text(item.name) == norm_name
                and _normalize_text(item.location) == norm_loc
            ):
                match_idx = idx
                break

        if match_idx is not None:
            preserved_id = existing[match_idx].id
            updated = recruiter.model_copy(update={"id": preserved_id})
            existing[match_idx] = updated
            result = updated
        else:
            existing.append(recruiter)
            result = recruiter

        self._write_models(self.config.recruiters_file, existing)
        return result

    def seed_initial_recruiters(
        self, initial_recruiters: list[Recruiter] | None = None
    ) -> list[Recruiter]:
        """Garante cadastro dos recrutadores sem sobrescrever os já existentes."""
        existing = self.list_recruiters()
        if not initial_recruiters:
            if not self.config.recruiters_file.exists():
                self._write_models(self.config.recruiters_file, existing)
            return existing

        existing_ids = {r.id for r in existing}
        existing_names = {_normalize_text(r.name) for r in existing}

        changed = False
        for seed_rec in initial_recruiters:
            if (
                seed_rec.id not in existing_ids
                and _normalize_text(seed_rec.name) not in existing_names
            ):
                existing.append(seed_rec)
                existing_ids.add(seed_rec.id)
                existing_names.add(_normalize_text(seed_rec.name))
                changed = True

        if changed or not self.config.recruiters_file.exists():
            self._write_models(self.config.recruiters_file, existing)

        return existing

    # ------------------------------------------------------------------
    # Empresas
    # ------------------------------------------------------------------

    def list_companies(self) -> list[Company]:
        return self._read_models(self.config.companies_file, Company)

    def get_company(self, company_id: str) -> Company | None:
        target = company_id.strip()
        for comp in self.list_companies():
            if comp.id == target:
                return comp
        return None

    def upsert_company(self, company: Company) -> Company:
        """Insere ou atualiza empresa deduplicando por id, linkedin_url ou nome normalizado."""
        existing = self.list_companies()
        norm_url = _normalize_url(company.linkedin_url)
        norm_name = _normalize_text(company.name)

        match_idx: int | None = None
        for idx, item in enumerate(existing):
            if item.id == company.id:
                match_idx = idx
                break
            if norm_url and _normalize_url(item.linkedin_url) == norm_url:
                match_idx = idx
                break
            if _normalize_text(item.name) == norm_name:
                match_idx = idx
                break

        if match_idx is not None:
            preserved_id = existing[match_idx].id
            updated = company.model_copy(update={"id": preserved_id})
            existing[match_idx] = updated
            result = updated
        else:
            existing.append(company)
            result = company

        self._write_models(self.config.companies_file, existing)
        return result

    # ------------------------------------------------------------------
    # Vagas
    # ------------------------------------------------------------------

    def list_jobs(self) -> list[Job]:
        return self._read_models(self.config.jobs_file, Job)

    def get_job(self, job_id: str) -> Job | None:
        target = job_id.strip()
        for job in self.list_jobs():
            if job.id == target:
                return job
        return None

    def upsert_job(self, job: Job) -> Job:
        """Insere ou atualiza vaga deduplicando por id, URL ou (título, empresa, local)."""
        existing = self.list_jobs()
        norm_url = _normalize_url(job.application_url)
        norm_key = (
            _normalize_text(job.title),
            _normalize_text(job.company),
            _normalize_text(job.location),
        )

        match_idx: int | None = None
        for idx, item in enumerate(existing):
            if item.id == job.id:
                match_idx = idx
                break
            if norm_url and _normalize_url(item.application_url) == norm_url:
                match_idx = idx
                break
            item_key = (
                _normalize_text(item.title),
                _normalize_text(item.company),
                _normalize_text(item.location),
            )
            if item_key == norm_key:
                match_idx = idx
                break

        if match_idx is not None:
            preserved_id = existing[match_idx].id
            updated = job.model_copy(update={"id": preserved_id})
            existing[match_idx] = updated
            result = updated
        else:
            existing.append(job)
            result = job

        self._write_models(self.config.jobs_file, existing)
        return result

    # ------------------------------------------------------------------
    # Mensagens Sugeridas / Contatos
    # ------------------------------------------------------------------

    def list_messages(self, recruiter_id: str | None = None) -> list[SuggestedMessage]:
        messages = self._read_models(self.config.contacts_file, SuggestedMessage)
        if recruiter_id is not None:
            return [m for m in messages if m.recruiter_id == recruiter_id]
        return messages

    def get_message(self, message_id: str) -> SuggestedMessage | None:
        """Obtém uma mensagem específica pelo identificador."""
        target = message_id.strip()
        for msg in self.list_messages():
            if msg.id == target:
                return msg
        return None

    def upsert_message(self, message: SuggestedMessage) -> SuggestedMessage:
        """Insere ou atualiza rascunho de mensagem por id."""
        existing = self.list_messages()
        match_idx: int | None = None
        for idx, item in enumerate(existing):
            if item.id == message.id:
                match_idx = idx
                break

        if match_idx is not None:
            existing[match_idx] = message
        else:
            existing.append(message)

        self._write_models(self.config.contacts_file, existing)
        return message
