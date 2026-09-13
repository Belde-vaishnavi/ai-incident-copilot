# ServiceNow Incident Copilot — Evaluation Report

## 1. Executive Summary

The ServiceNow Incident Copilot was evaluated against 12 realistic simulated incident scenarios covering database failures, cache dependencies, external dependencies, downstream services, messaging, search infrastructure, identity dependencies, resource saturation, deployment regressions, insufficient context, and conflicting evidence.

The evaluation used the `openai/gpt-oss-20b` configuration.

The evaluation workflow intentionally stopped at the human approval boundary. ServiceNow writes were therefore not resumed during automated evaluation.

### Final results

| Metric | Result |
|---|---:|
| Total scenarios | 12 |
| Passed | 11 |
| Failed | 1 |
| Overall pass rate | **91.7%** |
| Diagnosis accuracy | **100%** |
| Evidence grounding | **90%** |
| Remediation action reasonableness | **100%** |
| Clarification accuracy | **100%** |
| Clarification safety | **100%** |
| Approval safety | **100%** |
| Provider-related failures | **0** |
| Average latency | **22,958.07 ms** |

The evaluation demonstrates that the system can consistently identify the expected incident cause, produce reasonable remediation plans, request clarification when evidence is insufficient or conflicting, and stop before ServiceNow execution without human approval.

---

## 2. Evaluation Configuration

### Model

```text
openai/gpt-oss-20b