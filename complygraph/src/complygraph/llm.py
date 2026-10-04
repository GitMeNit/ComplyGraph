"""LLM provider abstraction. `offline` makes every caller use its deterministic heuristic."""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from .config import Settings


class LLM:
    name = "base"
    is_offline = False

    def complete(self, system: str, prompt: str, max_tokens: int = 1200) -> str:
        raise NotImplementedError

    def complete_json(self, system: str, prompt: str):
        text = self.complete(system + "\nReturn ONLY valid JSON.", prompt)
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        return json.loads(m.group(1)) if m else None


class OfflineLLM(LLM):
    name, is_offline = "offline-deterministic", True

    def complete(self, system, prompt, max_tokens=1200):
        return ""


class AnthropicLLM(LLM):
    def __init__(self, model: str):
        import anthropic

        self.client, self.model, self.name = anthropic.Anthropic(), model, f"anthropic:{model}"

    def complete(self, system, prompt, max_tokens=1200):
        r = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}], temperature=0,
        )
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")


class OpenAICompatLLM(LLM):
    """OpenAI, Azure OpenAI (via OPENAI_BASE_URL) or any compatible gateway."""

    def __init__(self, model: str):
        from openai import OpenAI

        self.client, self.model, self.name = OpenAI(), model, f"openai:{model}"

    def complete(self, system, prompt, max_tokens=1200):
        r = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        )
        return r.choices[0].message.content or ""


def get_llm(settings: Optional[Settings] = None) -> LLM:
    s = settings or Settings.load()
    try:
        if s.llm_provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
            return AnthropicLLM(s.llm_model)
        if s.llm_provider == "openai" and os.environ.get("OPENAI_API_KEY"):
            return OpenAICompatLLM(s.llm_model)
    except Exception:  # missing SDK / bad config -> degrade safely, never crash the control plane
        pass
    return OfflineLLM()
