from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod

import httpx

from .models import ModelReview, ReviewIssue


def _compact_repo_context(repo_context: dict, max_files: int, max_file_chars: int) -> dict:
    files = repo_context.get("files", [])[:max_files]
    compact_files: list[dict] = []
    for file in files:
        compact_files.append(
            {
                "path": file.get("path"),
                "language": file.get("language"),
                "size_chars": file.get("size_chars"),
                "line_count": file.get("line_count"),
                "content": str(file.get("content", ""))[:max_file_chars],
            }
        )

    return {
        "repo_name": repo_context.get("repo_name"),
        "branch": repo_context.get("branch"),
        "commit": repo_context.get("commit"),
        "stats": repo_context.get("stats", {}),
        "files": compact_files,
    }


def _build_review_prompt(repo_context: dict, max_prompt_chars: int = 120000) -> str:
    return (
        "You are a senior principal engineer performing a production-grade code review. "
        "Return STRICT JSON with keys: summary (string), strengths (array[string]), risk_score (0-100 int), "
        "issues (array of objects with title, severity[critical|high|medium|low], category, file, line(optional int), suggestion, rationale, confidence[0-1]). "
        "Return only valid JSON without markdown/code fences. Keep issues <= 10 and keep each rationale concise.\n\n"
        f"Repository Context:\n{json.dumps(repo_context, ensure_ascii=False)[:max_prompt_chars]}"
    )


def _extract_json_payload(text: str) -> dict | None:
    cleaned = text.strip()
    if not cleaned:
        return None

    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    first_brace = cleaned.find("{")
    if first_brace == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    end_index = -1

    for idx in range(first_brace, len(cleaned)):
        char = cleaned[idx]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end_index = idx + 1
                break

    candidate = cleaned[first_brace:end_index] if end_index != -1 else cleaned[first_brace:]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _parse_response_to_review(
    model_name: str,
    family: str,
    text: str,
) -> ModelReview:
    payload = _extract_json_payload(text)
    if payload is None:
        cleaned = text.strip()
        fallback_summary = cleaned[:600] if cleaned else "Model returned an empty response."
        fallback_error = (
            "Model did not return valid JSON; raw response retained."
            if cleaned
            else "Model returned an empty response."
        )
        return ModelReview(
            model_name=model_name,
            family=family,
            enabled=True,
            summary=fallback_summary,
            strengths=[],
            issues=[],
            risk_score=50,
            raw_response=cleaned,
            error=fallback_error,
        )

    issues: list[ReviewIssue] = []
    for issue in payload.get("issues", []):
        try:
            issues.append(
                ReviewIssue(
                    title=issue.get("title", "Unspecified issue"),
                    severity=issue.get("severity", "medium"),
                    category=issue.get("category", "general"),
                    file=issue.get("file", "repository-wide"),
                    line=issue.get("line"),
                    suggestion=issue.get("suggestion", "No suggestion provided."),
                    rationale=issue.get("rationale", "No rationale provided."),
                    confidence=float(issue.get("confidence", 0.5)),
                    source_model=model_name,
                )
            )
        except Exception:
            continue

    summary = str(payload.get("summary", "")).strip() or "Model response parsed, but summary was missing."

    return ModelReview(
        model_name=model_name,
        family=family,
        enabled=True,
        summary=summary,
        strengths=payload.get("strengths", []),
        issues=issues,
        risk_score=int(payload.get("risk_score", 50)),
        raw_response=text,
    )


class LLMProvider(ABC):
    name: str
    family: str

    @abstractmethod
    def enabled(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def review(self, repo_context: dict) -> ModelReview:
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    name = "OpenAI Reviewer"
    family = "openai"

    def enabled(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    async def review(self, repo_context: dict) -> ModelReview:
        if not self.enabled():
            return ModelReview(model_name=self.name, family=self.family, enabled=False, error="OPENAI_API_KEY is missing")

        model = os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
        compact_context = _compact_repo_context(repo_context, max_files=14, max_file_chars=2400)
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You produce strict JSON only."},
                {"role": "user", "content": _build_review_prompt(compact_context, max_prompt_chars=85000)},
            ],
            "temperature": 0.2,
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
                response.raise_for_status()
                text = response.json()["choices"][0]["message"]["content"]
            return _parse_response_to_review(self.name, self.family, text)
        except Exception as exc:
            return ModelReview(model_name=self.name, family=self.family, enabled=True, error=str(exc))


class AnthropicProvider(LLMProvider):
    name = "Anthropic Reviewer"
    family = "anthropic"

    def enabled(self) -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY"))

    async def review(self, repo_context: dict) -> ModelReview:
        if not self.enabled():
            return ModelReview(model_name=self.name, family=self.family, enabled=False, error="ANTHROPIC_API_KEY is missing")

        model = os.getenv("ANTHROPIC_MODEL") or "claude-3-5-sonnet-20241022"
        compact_context = _compact_repo_context(repo_context, max_files=12, max_file_chars=2000)
        headers = {
            "x-api-key": os.getenv("ANTHROPIC_API_KEY", ""),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": 2200,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": _build_review_prompt(compact_context, max_prompt_chars=70000)}],
            "system": "You produce strict JSON only.",
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
                response.raise_for_status()
                chunks = response.json().get("content", [])
                text = "\n".join(part.get("text", "") for part in chunks if part.get("type") == "text")
            return _parse_response_to_review(self.name, self.family, text)
        except Exception as exc:
            return ModelReview(model_name=self.name, family=self.family, enabled=True, error=str(exc))


class GroqProvider(LLMProvider):
    name = "Groq Reviewer"
    family = "groq"

    def enabled(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))

    async def review(self, repo_context: dict) -> ModelReview:
        if not self.enabled():
            return ModelReview(model_name=self.name, family=self.family, enabled=False, error="GROQ_API_KEY is missing")

        model = os.getenv("GROQ_MODEL") or "llama-3.1-8b-instant"
        compact_context = _compact_repo_context(repo_context, max_files=8, max_file_chars=1200)
        prompt = _build_review_prompt(compact_context, max_prompt_chars=22000)
        headers = {
            "Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You produce strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 1800,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=body)
                if response.status_code == 413:
                    smaller_context = _compact_repo_context(repo_context, max_files=5, max_file_chars=700)
                    smaller_body = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "You produce strict JSON only."},
                            {"role": "user", "content": _build_review_prompt(smaller_context, max_prompt_chars=12000)},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1400,
                        "response_format": {"type": "json_object"},
                    }
                    response = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers=headers,
                        json=smaller_body,
                    )

                response.raise_for_status()
                text = response.json()["choices"][0]["message"]["content"]
            return _parse_response_to_review(self.name, self.family, text)
        except Exception as exc:
            return ModelReview(model_name=self.name, family=self.family, enabled=True, error=str(exc))


class OllamaProvider(LLMProvider):
    name = "Ollama Reviewer"
    family = "open-source-local"

    def enabled(self) -> bool:
        return True

    @staticmethod
    def _normalize_endpoint(endpoint: str) -> str:
        base = endpoint.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        if base.endswith("/api"):
            base = base[: -len("/api")]
        return base

    async def _list_models(self, client: httpx.AsyncClient, endpoint: str) -> list[str]:
        try:
            response = await client.get(f"{endpoint}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
            return [m.get("name", "") for m in models if m.get("name")]
        except Exception:
            return []

    async def _fallback_model(self, client: httpx.AsyncClient, endpoint: str, preferred: str) -> str | None:
        models = await self._list_models(client, endpoint)
        if not models:
            return None

        preferred_lower = preferred.lower()
        for model in models:
            if preferred_lower in model.lower() or model.lower() in preferred_lower:
                return model
        return models[0]

    async def _generate_native(self, client: httpx.AsyncClient, endpoint: str, model: str, prompt: str) -> str:
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }
        response = await client.post(f"{endpoint}/api/generate", json=body)
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(str(payload.get("error")))
        return str(payload.get("response", ""))

    async def _generate_openai_compat(self, client: httpx.AsyncClient, endpoint: str, model: str, prompt: str) -> str:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You produce strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        response = await client.post(f"{endpoint}/v1/chat/completions", json=body)
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("choices", [{}])[0].get("message", {}).get("content", ""))

    async def review(self, repo_context: dict) -> ModelReview:
        if not self.enabled():
            return ModelReview(model_name=self.name, family=self.family, enabled=False, error="OLLAMA_ENDPOINT is missing")

        endpoint = self._normalize_endpoint(os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434"))
        model = os.getenv("OLLAMA_MODEL") or "llama3:8b"
        compact_context = _compact_repo_context(repo_context, max_files=20, max_file_chars=4000)
        prompt = _build_review_prompt(compact_context, max_prompt_chars=150000)
        used_model = model

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                try:
                    text = await self._generate_native(client, endpoint, model, prompt)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                    text = await self._generate_openai_compat(client, endpoint, model, prompt)
                except RuntimeError as exc:
                    if "not found" not in str(exc).lower():
                        raise
                    fallback = await self._fallback_model(client, endpoint, model)
                    if not fallback:
                        return ModelReview(
                            model_name=self.name,
                            family=self.family,
                            enabled=True,
                            error=f"Ollama model '{model}' not found and no local models are available.",
                        )
                    used_model = fallback
                    try:
                        text = await self._generate_native(client, endpoint, fallback, prompt)
                    except httpx.HTTPStatusError as retry_exc:
                        if retry_exc.response.status_code != 404:
                            raise
                        text = await self._generate_openai_compat(client, endpoint, fallback, prompt)
                if not text.strip():
                    return ModelReview(
                        model_name=self.name,
                        family=self.family,
                        enabled=True,
                        summary=f"Ollama model '{used_model}' responded but returned empty content.",
                        error="Ollama returned an empty response for the selected model.",
                    )
            parsed = _parse_response_to_review(self.name, self.family, text)
            parsed.summary = f"Model: {used_model}. {parsed.summary}"
            return parsed
        except Exception as exc:
            return ModelReview(model_name=self.name, family=self.family, enabled=True, error=str(exc))


class GeminiProvider(LLMProvider):
    name = "Gemini Reviewer"
    family = "google-gemini"

    def enabled(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY"))

    async def review(self, repo_context: dict) -> ModelReview:
        if not self.enabled():
            return ModelReview(model_name=self.name, family=self.family, enabled=False, error="GEMINI_API_KEY is missing")

        model = os.getenv("GEMINI_MODEL") or "gemini-1.5-flash"
        compact_context = _compact_repo_context(repo_context, max_files=10, max_file_chars=1500)
        prompt = _build_review_prompt(compact_context, max_prompt_chars=30000)
        api_key = os.getenv("GEMINI_API_KEY", "")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                payload = response.json()
                candidates = payload.get("candidates", [])
                parts = (
                    candidates[0].get("content", {}).get("parts", [])
                    if candidates
                    else []
                )
                text = "\n".join(str(part.get("text", "")) for part in parts)
            return _parse_response_to_review(self.name, self.family, text)
        except Exception as exc:
            return ModelReview(model_name=self.name, family=self.family, enabled=True, error=str(exc))


def get_default_providers() -> list[LLMProvider]:
    return [OpenAIProvider(), AnthropicProvider(), GroqProvider(), GeminiProvider(), OllamaProvider()]
