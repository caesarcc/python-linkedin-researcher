"""Provedor de inferência local via Ollama com saída estruturada Pydantic."""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class OllamaProvider:
    """Implementa inferência local 100% privada utilizando Ollama."""

    def __init__(
        self,
        model: str = "qwen2.5:3b",
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
        client: Any | None = None,
    ) -> None:
        self._model = model.strip() or "qwen2.5:3b"
        self._base_url = base_url.strip() or "http://localhost:11434"
        self._timeout = timeout
        self._client = client

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import ollama

        self._client = ollama.Client(host=self._base_url, timeout=self._timeout)
        return self._client

    def is_available(self) -> bool:
        """Verifica se o servidor Ollama está respondendo e se o modelo configurado existe."""
        try:
            available_models: list[str] = []
            if self._client is not None:
                models_list = self._client.list()
                if hasattr(models_list, "models"):
                    for m in models_list.models:
                        name = getattr(m, "model", "") or getattr(m, "name", "")
                        if name:
                            available_models.append(name.casefold())
                elif isinstance(models_list, dict) and "models" in models_list:
                    for m in models_list["models"]:
                        name = m.get("model", "") or m.get("name", "")
                        if name:
                            available_models.append(name.casefold())
            else:
                import httpx

                resp = httpx.get(f"{self._base_url}/api/tags", timeout=1.0)
                if resp.status_code != 200:
                    return False
                data = resp.json()
                for m in data.get("models", []):
                    name = m.get("model", "") or m.get("name", "")
                    if name:
                        available_models.append(name.casefold())

            # Verifica se o modelo exato ou sua versão sem tag está na lista
            model_base = self._model.casefold().split(":")[0]
            for m in available_models:
                if self._model.casefold() in m or m.startswith(model_base):
                    return True

            logger.info(
                "Ollama está online em %s, mas o modelo '%s' ainda não foi baixado. "
                "Execute 'ollama pull %s' para ativá-lo.",
                self._base_url,
                self._model,
                self._model,
            )
            return False
        except Exception as exc:
            logger.debug("Servidor Ollama indisponível em %s: %s", self._base_url, exc)
            return False

    def generate_structured(self, prompt: str, schema: type[T]) -> T | None:
        """Gera resposta formatada via JSON Schema nativo do Ollama e valida com Pydantic."""
        try:
            client = self._get_client()
            response = client.chat(
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                format=schema.model_json_schema(),
                options={"temperature": 0.0},
            )

            content = ""
            if hasattr(response, "message") and hasattr(response.message, "content"):
                content = response.message.content or ""
            elif isinstance(response, dict) and "message" in response:
                content = response["message"].get("content", "")

            if not content:
                logger.warning("Resposta vazia do Ollama para o modelo '%s'.", self._model)
                return None

            return schema.model_validate_json(content)
        except Exception as exc:
            logger.warning(
                "Falha na inferência via Ollama (%s: %s). Ativando fallback determinístico.",
                self._model,
                exc,
            )
            return None
