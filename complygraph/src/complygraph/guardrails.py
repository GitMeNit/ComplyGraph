"""Deterministic runtime guardrails (no LLM in the enforcement path).

Input : length cap, prompt-injection patterns, PII redaction before anything reaches a model/log.
Output: forbidden phrases, citation integrity (every [R#] must exist in retrieved evidence),
        PII leak redaction, mandatory disclaimer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_PII = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("API_KEY", re.compile(r"\b(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("PHONE", re.compile(r"(?<![\w/])\+?\d[\d\s().-]{8,}\d(?![\w/])")),
]
CITE = re.compile(r"\[R(\d+)\]")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


def redact(text: str) -> tuple[str, dict]:
    counts: dict = {}
    for label, rx in _PII:
        def sub(m, label=label):
            raw = re.sub(r"\D", "", m.group(0))
            if label == "CARD" and not (13 <= len(raw) <= 19 and _luhn(raw)):
                return m.group(0)
            if label == "PHONE" and not (9 <= len(raw) <= 15):
                return m.group(0)
            counts[label] = counts.get(label, 0) + 1
            return f"[REDACTED:{label}]"
        text = rx.sub(sub, text)
    return text, counts


@dataclass
class GuardResult:
    allowed: bool
    text: str
    violations: list = field(default_factory=list)
    redactions: dict = field(default_factory=dict)


class Guardrails:
    def __init__(self, policies_path: Path):
        self.policy = yaml.safe_load(Path(policies_path).read_text())
        self._inj = [re.compile(p, re.I) for p in self.policy["input"]["block_patterns"]]

    @property
    def disclaimer(self) -> str:
        return self.policy["output"]["disclaimer"]

    def check_input(self, text: str) -> GuardResult:
        if len(text) > self.policy["input"]["max_chars"]:
            return GuardResult(False, "", ["input_too_long"])
        for rx in self._inj:
            if rx.search(text):
                return GuardResult(False, "", ["prompt_injection_suspected"])
        clean, counts = redact(text)
        return GuardResult(True, clean, [], counts)

    def check_output(self, text: str, valid_refs: set, used_rag: bool, abstained: bool = False) -> GuardResult:
        out = self.policy["output"]
        low = text.lower()
        violations = [f"forbidden_phrase:{p}" for p in out["forbidden_phrases"] if p in low]
        cited = {int(n) for n in CITE.findall(text)}
        bad = sorted(n for n in cited if n not in valid_refs)
        if bad:
            violations.append(f"unknown_citation:{bad}")
        if used_rag and out["require_citations"] and not cited and not abstained:
            violations.append("missing_citations")
        clean, counts = redact(text)
        if out["disclaimer"] not in clean:
            clean = f"{clean.rstrip()}\n\n_{out['disclaimer']}_"
        return GuardResult(not violations, clean, violations, counts)
