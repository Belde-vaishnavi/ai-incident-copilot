# Design Notes — ServiceNow Incident Copilot

## 1. Overview

The ServiceNow Incident Copilot is designed as an evidence-grounded, human-in-the-loop incident investigation workflow.

The implementation uses LangGraph to make the workflow explicit rather than relying on a single chatbot response.

The workflow investigates an incident, evaluates whether enough evidence is available, generates a structured diagnosis, proposes a structured remediation plan, pauses for human approval, and only then performs an approved ServiceNow create/update operation.

The system is intentionally designed so that the LLM proposes and reasons, while deterministic application code controls workflow routing, validation and ServiceNow writes.

## 2. Why LangGraph / Explicit State Machine

LangGraph was selected because the assignment requires explicit workflow/state behavior and conditional paths.

The workflow state carries information between nodes, including:

- incident information,
- logs,
- metrics,
- runbook results,
- historical context,
- investigation status,
- evidence sufficiency,
- diagnosis,
- remediation plan,
- approval status,
- ServiceNow status,
- errors,
- run ID and retry information.

This makes the workflow easier to inspect and test than a single autonomous agent loop.

The graph also makes safety boundaries visible:

```text
Investigation
      |
Evidence Assessment
      |
Diagnosis
      |
Remediation Plan
      |
Human Approval
      |
ServiceNow Write
```

## 3. Agent Responsibilities

### Diagnosis Agent

The diagnosis agent is responsible for identifying the most likely root cause from available evidence.

It produces structured output containing:

- likely root cause,
- confidence,
- reasoning,
- evidence.

It is instructed not to invent evidence and not to execute remediation or ServiceNow actions.

### Remediation Agent

The remediation agent converts the diagnosis into a structured remediation plan.

It produces:

- recommended actions,
- operational risk,
- rollback plan,
- ServiceNow update content.

Every action must explicitly require approval.

The agent does not execute the remediation.

### Workflow / Graph Nodes

Deterministic graph nodes are responsible for:

- investigation,
- evidence assessment,
- routing,
- human approval,
- ServiceNow execution,
- clarification handling.

This division keeps LLM reasoning separate from operational control.

## 4. Tool Design and Typed Schemas

The project uses typed tool interfaces for the main investigation and ServiceNow operations.

The investigation tools include:

- `search_runbooks(query, service, severity)`
- `fetch_logs(service, start_time, end_time)`
- `fetch_metrics(service, start_time, end_time)`
- historical incident context retrieval

The ServiceNow operations include:

- `create_servicenow_incident(title, description, severity, work_notes)`
- `get_servicenow_incident(incident_id)`
- `update_servicenow_incident(incident_id, state, work_notes)`

The tools return structured success/error information rather than relying on unstructured strings.

Inputs are validated before external operations.

## 5. Investigation Strategy

The investigation combines multiple evidence sources:

### Logs

Logs provide timestamped operational symptoms such as errors, timeouts and request identifiers.

### Metrics

Metrics provide signals such as:

- latency,
- error rate,
- CPU,
- memory,
- dependency health.

### Runbooks

Runbooks provide operational knowledge relevant to the affected service and severity.

### Historical Incidents

Historical incidents provide supporting context from previous incidents.

Current evidence is prioritized over historical similarity. Historical information is used as supporting context rather than treated as proof of the current root cause.

## 6. Evidence-Grounded Diagnosis

A key design decision is that diagnosis must be supported by evidence actually available in the workflow state.

Diagnosis validation checks:

- root cause is non-empty,
- reasoning is non-empty,
- evidence is present,
- evidence sources are valid,
- cited sources exist in the investigation context,
- historical-only evidence cannot receive unrestricted confidence,
- single-source evidence has a confidence limitation,
- when multiple current evidence sources are available, the diagnosis should cite multiple sources.

This reduces unsupported or hallucinated root-cause claims.

## 7. Handling Insufficient and Conflicting Evidence

The system does not force a diagnosis when the evidence is inadequate.

Two important evaluation scenarios intentionally represent:

- insufficient context,
- conflicting evidence.

For these cases the workflow requests clarification instead of producing an unsafe diagnosis and remediation plan.

This is important because a good incident copilot should know when it does not have enough information.

## 8. Structured Remediation Plan

The remediation plan is represented by a Pydantic model.

It contains:

- `incident_summary`
- `likely_root_cause`
- `confidence`
- `evidence`
- `recommended_actions`
- `rollback_plan`
- `servicenow_update`

Recommended actions contain:

- action,
- risk,
- `requires_approval`.

The model validation requires `requires_approval=true` for every action.

The remediation plan also has consistency checks against the diagnosis and incident severity.

## 9. Human Approval / Safety Boundary

Human approval is the most important operational safety boundary.

The workflow pauses before ServiceNow writes.

The approval state can be:

- pending,
- approved,
- rejected.

If the user rejects the proposed plan, the workflow does not write to ServiceNow and instead follows the clarification/revision path.

The ServiceNow node independently checks the approval state.

Therefore, even if the LLM proposes an action, the model cannot directly cause a ServiceNow write.

## 10. ServiceNow Integration

The project integrates with a ServiceNow Personal Developer Instance.

The implementation supports the required operations:

- create incident,
- read incident details,
- update incident state/work notes,
- attach the AI-generated triage/remediation summary through work notes.

The ServiceNow credentials and instance URL are supplied through environment variables rather than hard-coded in source code.

The project does not contain real credentials in the repository.

## 11. Idempotency and Duplicate Prevention

ServiceNow creation/update operations include duplicate-prevention/idempotency handling.

An idempotency key is derived from the operation payload so repeated requests can be recognized.

This is important because network retries can otherwise cause duplicate incidents.

The workflow records whether an operation was:

- newly created,
- updated,
- or prevented as a duplicate.

The final ServiceNow status reflects the actual result rather than assuming every request was a new creation.

## 12. Error Handling and Retry Strategy

The LLM provider has bounded retry behavior for transient failures such as rate limiting.

Structured-output validation failures can also trigger a bounded retry.

Daily token/quota exhaustion is treated differently from transient rate limiting: the system fails fast rather than repeatedly retrying a condition that is unlikely to recover immediately.

The graph also tracks investigation/tool failures and allows bounded workflow retry before moving to clarification.

This avoids unbounded loops and excessive model/API usage.

## 13. Observability and Traceability

Each workflow run receives a run ID.

The tracer records:

- node name,
- execution status,
- latency,
- tool calls,
- tool inputs,
- tool outputs,
- approval decisions,
- ServiceNow operations,
- final outcome.

Sensitive values are redacted from trace data.

This allows an evaluator or operator to reconstruct what happened during an incident investigation.

The evaluation also records latency and failure categories.

## 14. Evaluation Strategy

The project includes 12 realistic simulated incidents rather than only one happy-path scenario.

The scenarios cover:

- database connection pool exhaustion,
- Redis/cache dependency failure,
- payment gateway degradation,
- database latency,
- downstream dependency degradation,
- message queue backlog,
- search cluster problems,
- identity dependency failure,
- CPU/memory saturation,
- deployment/configuration regression,
- insufficient evidence,
- conflicting evidence.

The evaluation checks:

- diagnosis accuracy,
- evidence grounding,
- remediation action reasonableness,
- clarification accuracy,
- clarification safety,
- approval safety,
- latency,
- failure categories.

The evaluation intentionally stops at the approval boundary and does not automatically perform ServiceNow writes.

## 15. Evaluation Result

The completed evaluation contains 12 scenarios.

Current evaluation results:

| Metric | Result |
|---|---:|
| Total scenarios | 12 |
| Passed | 11 |
| Failed | 1 |
| Overall pass rate | 91.7% |
| Diagnosis accuracy | 100% |
| Evidence grounding | 90% |
| Action reasonableness | 100% |
| Clarification accuracy | 100% |
| Clarification safety | 100% |
| Approval safety | 100% |
| Average latency | ~22.96 seconds |

The one remaining failure was an evidence-grounding case where the diagnosis was correct but did not cite the complete expected evidence set.

This is a useful evaluation finding because it shows that correct diagnosis alone is not sufficient; the system must also provide complete, traceable evidence.

## 16. Configuration Comparison

The evaluation was run with different model configurations during development.

The larger `openai/gpt-oss-120b` configuration encountered the provider daily token/quota limitation during an early evaluation run.

The project was subsequently configured to use:

```text
openai/gpt-oss-20b
```

through the OpenAI-compatible Groq endpoint.

The smaller model configuration successfully completed the full 12-case evaluation.

This demonstrated an important practical trade-off: model capability must be considered together with availability, quota, latency and cost.

The active model is configuration-driven through environment variables rather than hard-coded into the workflow.

## 17. Why the System Uses Simulated Context

The assignment explicitly allows simulated context for logs, metrics, runbooks and historical incidents.

The project therefore uses artificial but realistic SRE data to demonstrate the investigation workflow without requiring access to enterprise observability or knowledge systems.

The ServiceNow integration is demonstrated against a Personal Developer Instance.

In production, the simulated sources would be replaced by controlled enterprise integrations.

## 18. Security Considerations

The project follows several security-oriented principles:

- credentials are supplied through environment variables,
- secrets are excluded from Git,
- trace payloads redact sensitive values,
- ServiceNow writes require human approval,
- tool inputs are validated,
- external writes are idempotency-aware,
- remediation actions cannot be marked as not requiring approval.

Additional enterprise controls would still be required for production deployment.

## 19. Key Design Trade-off

The central trade-off is between LLM flexibility and deterministic safety.

A fully autonomous agent could potentially perform more actions with less orchestration code, but that would increase operational risk.

This implementation intentionally uses the LLM for:

- diagnosis,
- reasoning,
- remediation planning.

It uses deterministic application logic for:

- state transitions,
- validation,
- retries,
- approval,
- ServiceNow writes,
- failure handling.

This makes the system less autonomous than an unrestricted agent, but substantially safer and easier to audit.

## 20. Production Gaps

The current implementation is production-oriented but not production-ready.

Important production gaps include:

- simulated logs/metrics/runbooks/history instead of enterprise integrations,
- stronger authentication and authorization,
- RBAC for approval and ServiceNow operations,
- production-grade secret management,
- stronger monitoring and alerting,
- more extensive evaluation datasets,
- CI/CD and deployment hardening,
- distributed tracing,
- model cost controls,
- additional security and privacy controls,
- stronger resilience testing.

These are deliberate boundaries for a take-home implementation.

# Final Design Questions

## 21. Is This Production-Ready? Why or Why Not?

No. The system is **production-oriented but not production-ready**.

It demonstrates the core production-minded design:

- explicit workflow/state,
- typed tools,
- structured outputs,
- evidence validation,
- human approval,
- ServiceNow integration,
- duplicate prevention,
- bounded retries,
- observability,
- evaluation.

However, the investigation sources are simulated, and a production deployment would require enterprise integrations, stronger authentication/authorization, secret management, security controls, deployment hardening, broader testing and operational monitoring.

## 22. What Parts Are Mocked, and What Would Be Replaced in Production?

The following are simulated:

- logs,
- metrics,
- runbooks,
- historical incidents.

They are represented by realistic JSON datasets for the take-home demonstration.

In production, these would be replaced with controlled integrations to enterprise logging, monitoring/metrics, knowledge/runbook and incident-history systems.

The ServiceNow integration is implemented against a Personal Developer Instance for demonstration and would use production ServiceNow configuration and enterprise security controls in a real deployment.

## 23. If You Had One More Week, What Would You Improve?

I would prioritize:

1. stronger enterprise observability and distributed tracing,
2. more evaluation scenarios and automated regression evaluation,
3. improved retrieval/ranking for runbooks and historical incidents,
4. stronger RBAC and authentication/authorization,
5. production secret management,
6. CI/CD and deployment automation,
7. additional resilience and failure testing,
8. model cost/latency monitoring,
9. stronger privacy and sensitive-data controls,
10. production integrations for logs and metrics.

The goal would be to move the prototype from production-oriented architecture toward an operationally deployable system.

## 24. What Was the Hardest Trade-off You Made?

The hardest trade-off was balancing autonomous agent behavior with operational safety.

The system needs to demonstrate agentic reasoning, but allowing an LLM to directly perform ServiceNow changes would create an unsafe execution path.

Therefore, the design separates:

```text
LLM reasoning
      ↓
Structured plan
      ↓
Human approval
      ↓
Deterministic ServiceNow operation
```

This adds workflow complexity but provides a clear and auditable safety boundary.

## 25. What Are the Biggest Production Risks?

The biggest risks are:

1. **Incorrect diagnosis** — the model may interpret evidence incorrectly.
2. **Unsupported evidence** — the model could produce a plausible answer without sufficient evidence.
3. **Unsafe remediation recommendations** — a proposed action could cause an outage if applied incorrectly.
4. **Unauthorized writes** — ServiceNow changes must never bypass approval.
5. **Duplicate operations** — retries can create duplicate incidents without idempotency.
6. **External dependency failures** — ServiceNow, model providers or observability systems can fail.
7. **Model quota/cost/latency** — LLM usage can become expensive or unavailable.
8. **Sensitive information in traces** — operational logs can contain confidential data.
9. **Insufficient evaluation coverage** — performance on simulated scenarios may not represent every production incident.
10. **Human approval quality** — a human can approve an incorrect recommendation, so the approval UI and audit trail must remain strong.

The current implementation addresses several of these through evidence validation, structured outputs, human approval, idempotency, retries, redaction and observability, but production deployment would require additional controls.

## 26. Final Design Principle

The overall design can be summarized as:

> **The LLM reasons over evidence; the workflow controls the process; the human controls operational approval; and deterministic tools perform the approved ServiceNow operation.**
