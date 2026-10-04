# Control mapping - how ComplyGraph's own design maps to the rules it enforces

| Obligation | Reference | Implementation | Test |
|---|---|---|---|
| Automatic event logging / traceability | EU AI Act Art. 12; DORA Art. 9 | `audit.py` hash-chained, HMAC-optional log; every node emits events | `test_audit.py` |
| Human oversight, ability to override/stop | EU AI Act Art. 14; GDPR Art. 22 | `approvals.py` + `Copilot.n_gate`; four-eyes | `test_high_risk_scan_held_then_four_eyes` |
| Transparency / disclaimer | EU AI Act Art. 50 spirit; internal policy | `Guardrails.check_output` appends disclaimer; citations mandatory | `test_disclaimer_appended` |
| Data minimisation, PII protection | GDPR Art. 5(1)(c), 25, 32 | `guardrails.redact` before model + audit; truncated audit text | `test_pii_never_reaches_audit_log` |
| Robustness against prompt injection | NIST AI RMF (GenAI profile); OWASP LLM01 | deterministic input patterns, least-privilege tools, scan-root allowlist | `test_injection_*`, `test_scan_root_guard` |
| Effective challenge, validation evidence | SR 11-7 | deterministic guardrail tests; abstention + review on low confidence | `test_abstains_when_out_of_corpus` |
| Third-party exit / resilience | DORA Art. 28(8) | provider abstraction, offline fallback, MCP boundary | `OfflineLLM`, `build_toolbox` fallback |
| Accountability / segregation of duties | SR 11-7 governance; SOX-style maker-checker | requester != approver enforced and audited | `approval.denied_self_approval` event |

## Threat model (abridged)

| Threat | Mitigation | Residual risk |
|---|---|---|
| Prompt injection via user input | Pattern block + PII strip; LLM output cannot trigger tools directly (routing is lexical/enum-validated) | Novel phrasing evades regex - add classifier layer |
| Injection via scanned files / retrieved text | Scanner is regex-only (no LLM reads scanned code); only approved corpus is retrievable | Corpus poisoning if repo write access is loose - protect `data/` with CODEOWNERS |
| Hallucinated legal claims | Citations required and validated against retrieved set; abstain below threshold | Cited source may be summarised imprecisely - corpus must be curated |
| Audit log tampering | Hash chain + HMAC + WORM replication | Whole-file replacement without HMAC key rotation controls |
| Path traversal via tool args | `allowed_scan_path` allowlist | Symlinks resolved via `Path.resolve()` |
| Self-approval / collusion | Four-eyes; audit of denied attempts | Two colluding users - add approver pools and SoD reports |
