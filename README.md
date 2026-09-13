# AI Incident Copilot

A lightweight, production-minded AI Incident Copilot for SRE workflows.

The system accepts an incident description, investigates the incident using structured logs, metrics, runbooks, and historical incident context, reasons about a likely root cause, generates a structured remediation plan, and requires explicit human approval before performing ServiceNow writes.

This project is implemented as an explicit agentic workflow rather than a simple chatbot.

---

## 1. Project Overview

The AI Incident Copilot demonstrates an agentic incident-response workflow with:

- Explicit LangGraph state and orchestration
- Multiple typed investigation tools
- Simulated operational data
- Evidence-grounded diagnosis
- Structured remediation planning
- Human-in-the-loop approval
- ServiceNow Personal Developer Instance (PDI) integration
- Duplicate-prevention and safe ServiceNow writes
- Bounded LLM retry handling
- Observability and trace logging
- Automated evaluation across 12 incident scenarios

The project intentionally uses simulated logs, metrics, runbooks, and historical incident context so that the take-home can be demonstrated without connecting to real production monitoring systems.

ServiceNow integration uses a Personal Developer Instance (PDI), not a production company tenant.

---

## 2. Architecture

The system uses an explicit LangGraph `StateGraph`.

```text
                         +----------------------+
                         |      SRE / User      |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         |    Incident Input    |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         |    LangGraph State   |
                         +----------+-----------+
                                    |
                                    v
              +---------------------+---------------------+
              |                     |                     |
              v                     v                     v
        +-----------+         +-----------+        +-------------+
        |   Logs    |         |  Metrics  |        |  Runbooks   |
        |   Tool    |         |   Tool    |        |    Tool     |
        +-----------+         +-----------+        +-------------+
              |                     |                     |
              +---------------------+---------------------+
                                    |
                                    v
                         +----------------------+
                         | Historical Incidents |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         |  Evidence Analysis   |
                         +----------+-----------+
                                    |
                         +----------+----------+
                         |                     |
                       Insufficient          Sufficient
                       / Conflicting             |
                         |                       v
                         v             +-------------------+
                +----------------+     |     Diagnosis     |
                |  Clarification |     | + Confidence      |
                +----------------+     +---------+---------+
                                               |
                                               v
                                      +-------------------+
                                      | Remediation Plan  |
                                      +---------+---------+
                                                |
                                                v
                                      +-------------------+
                                      |  Human Approval   |
                                      +---------+---------+
                                                |
                                  +-------------+-------------+
                                  |                           |
                               Rejected                    Approved
                                  |                           |
                                  v                           v
                         +----------------+        +----------------------+
                         | Revise/Clarify |        |     ServiceNow       |
                         +----------------+        | Create / Update PDI  |
                                                   +----------+-----------+
                                                              |
                                                              v
                                                   +----------------------+
                                                   |    Final Outcome     |
                                                   +----------+-----------+
                                                              |
                                                              v
                                                   +----------------------+
                                                   |    Observability     |
                                                   +----------------------+
```

---

## 3. Core Workflow

### Step 1 — Incident Input

The workflow accepts:

- Incident ID
- Service
- Severity
- Title
- Description
- Investigation start time
- Investigation end time

### Step 2 — Investigation

The investigation node collects structured context from:

- Logs
- Metrics
- Runbooks
- Historical incidents

Each source is represented using typed schemas.

The investigation data is kept in the shared LangGraph state.

### Step 3 — Evidence Assessment

The workflow evaluates whether the available evidence is sufficient.

It distinguishes between:

- Sufficient evidence
- Insufficient evidence
- Conflicting evidence
- Tool failures

If evidence is insufficient or conflicting, the system does not force a diagnosis.

Instead, it requests clarification.

Tool failures use a bounded retry path before falling back to clarification.

### Step 4 — Diagnosis

The diagnosis agent receives structured investigation evidence and produces:

- Likely root cause
- Confidence score
- Reasoning
- Evidence references

The diagnosis is constrained to available evidence.

Additional validation checks:

- Root cause must be non-empty
- Reasoning must be non-empty
- Evidence must reference available sources
- Confidence must be between 0 and 1
- Historical-only evidence cannot produce excessive confidence
- Single-source diagnoses are confidence-limited
- Multiple available current evidence sources should be represented where appropriate

### Step 5 — Remediation Planning

The remediation agent produces a structured JSON remediation plan containing:

- Incident summary
- Likely root cause
- Confidence
- Supporting evidence
- Recommended actions
- Risk for each action
- Approval requirement
- Rollback plan
- ServiceNow update content

Every remediation action is required to have:

```text
requires_approval = true
```

The remediation output is validated using Pydantic schemas.

Invalid structured output is handled through bounded retry logic.

### Step 6 — Human Approval

Before any ServiceNow side effect, the workflow reaches an explicit human approval boundary.

The proposed remediation is presented to the human.

Possible outcomes:

```text
Approved
Rejected
```

A rejection does not result in a ServiceNow write.

The workflow can instead revise the plan or request clarification.

### Step 7 — ServiceNow

After explicit approval, the system can interact with the ServiceNow PDI.

Supported operations include:

- Create incident
- Read incident details
- Update incident state
- Update work notes
- Attach AI-generated triage/remediation information to work notes

ServiceNow writes are protected by:

- Human approval
- Input validation
- Duplicate prevention
- Idempotency handling
- Structured success/error responses
- Tool-call tracing

The automated evaluation intentionally stops at the approval boundary and does not resume the graph, so evaluation cannot accidentally perform a ServiceNow write.

---

## 4. Typed Tools

### `search_runbooks(query, service, severity)`

Searches simulated runbooks and returns structured matches.

Example information:

```text
source_id
title
snippet
relevance_reasoning
```

### `fetch_logs(service, start_time, end_time)`

Returns structured log records containing:

```text
timestamp
service
level
message
error
request_id
```

### `fetch_metrics(service, start_time, end_time)`

Returns structured operational metrics including:

```text
timestamp
latency_ms
error_rate
cpu_percent
memory_percent
dependency_health
```

### Historical incident retrieval

Retrieves relevant historical incident context from the simulated dataset.

Historical incidents are treated as supporting context rather than definitive proof.

### `create_servicenow_incident(...)`

Creates an incident in the ServiceNow PDI.

This is a side-effecting operation and is protected by the human approval boundary.

### `update_servicenow_incident(...)`

Updates a ServiceNow PDI incident with:

- State
- Work notes
- AI-generated investigation/remediation information

This is also protected by the approval boundary.

---

## 5. Structured Remediation Schema

The remediation plan follows a typed structure similar to:

```json
{
  "incident_summary": "string",
  "likely_root_cause": "string",
  "confidence": 0.95,
  "evidence": [
    {
      "source": "logs",
      "detail": "string"
    }
  ],
  "recommended_actions": [
    {
      "action": "string",
      "risk": "medium",
      "requires_approval": true
    }
  ],
  "rollback_plan": "string",
  "servicenow_update": {
    "short_description": "string",
    "severity": "P1",
    "work_notes": "string"
  }
}
```

The output is validated before being accepted by the workflow.

---

## 6. Safety Model

ServiceNow is treated as a side-effecting external system.

The application therefore separates:

```text
Reasoning
    |
    v
Recommendation
    |
    v
Human Approval
    |
    v
ServiceNow Side Effect
```

The LLM does not directly decide whether to execute a ServiceNow write.

### Safety controls

- Human approval before every ServiceNow write
- Typed tool inputs and outputs
- Input validation
- Bounded retry logic
- Duplicate prevention
- Idempotency support
- Structured errors
- Sensitive-value redaction in traces
- Credentials stored in environment variables
- `.env` excluded from Git
- Automated evaluation stops before ServiceNow execution
- No remediation execution without explicit approval

---

## 7. Simulated Data

The project includes realistic simulated SRE scenarios.

The dataset covers:

1. Database connection pool exhaustion
2. Redis/cache dependency failure
3. External payment gateway degradation
4. Database latency
5. Downstream inventory dependency degradation
6. Message queue backlog
7. Search cluster degradation
8. Identity provider failure
9. CPU/memory saturation
10. Deployment configuration regression
11. Insufficient context
12. Conflicting evidence

The simulated data allows the workflow to be evaluated repeatably without requiring production monitoring access.

---

## 8. Project Structure

```text
ServiceNow-Incident-Copilot/
│
├── app/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── diagnosis_agent.py
│   │   └── remediation_agent.py
│   │
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py
│   │   ├── nodes.py
│   │   ├── edges.py
│   │   ├── graph_builder.py
│   │   └── servicenow_node.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── incident.py
│   │   ├── investigation.py
│   │   ├── diagnosis.py
│   │   ├── remediation.py
│   │   └── servicenow.py
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── runbook_tools.py
│   │   ├── log_tools.py
│   │   ├── metric_tools.py
│   │   ├── historical_tools.py
│   │   └── servicenow_tools.py
│   │
│   ├── data/
│   │   ├── incidents.json
│   │   ├── logs.json
│   │   ├── metrics.json
│   │   ├── runbooks.json
│   │   └── historical_incidents.json
│   │
│   ├── prompts/
│   │   ├── diagnosis_prompt.py
│   │   └── remediation_prompt.py
│   │
│   ├── llm/
│   │   └── provider.py
│   │
│   ├── observability/
│   │   ├── context.py
│   │   └── tracer.py
│   │
│   └── main.py
│
├── evaluation/
│   ├── incidents.json
│   ├── evaluate.py
│   ├── evaluation_results.json
│   └── evaluation_report.md
│
├── docs/
│   ├── architecture.md
│   └── design_notes.md
│
├── tests/
│   └── test_graph.py
│
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

---

## 9. Configuration

All LLM and ServiceNow configuration is externalized through environment variables.

Create a local `.env` file in the project root.

Example:

```env
API_KEY=

GROK_MODEL=
GROK_BASE_URL=

SERVICENOW_INSTANCE=
SERVICENOW_USERNAME=
SERVICENOW_PASSWORD=
```

The project currently uses:

```text
API_KEY
GROK_MODEL
GROK_BASE_URL
SERVICENOW_INSTANCE
SERVICENOW_USERNAME
SERVICENOW_PASSWORD
```

The model is configuration-driven and does not need to be supplied on every execution command.

The `.env` file must never be committed to Git.

Use `.env.example` as the safe configuration template.

---

## 10. Local Setup

### Create virtual environment

```bash
python -m venv .venv
```

### Windows activation

```powershell
.venv\Scripts\activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure environment

Copy:

```text
.env.example
```

to:

```text
.env
```

Then fill in the required values.

---

## 11. Run the Application

After configuring `.env`:

```bash
python -m app.main
```

The application investigates the configured incident and displays the diagnosis and remediation plan.

For a normal incident, the workflow stops at:

```text
Approve remediation? [y/n]:
```

A ServiceNow write occurs only when the human explicitly approves.

---

## 12. ServiceNow PDI

The project uses a ServiceNow Personal Developer Instance.

Required environment variables:

```env
SERVICENOW_INSTANCE=
SERVICENOW_USERNAME=
SERVICENOW_PASSWORD=
```

The application supports:

```text
Create incident
Read incident
Update incident
Update work notes
```

The AI-generated investigation and remediation summary can be written into ServiceNow work notes after approval.

A real company ServiceNow tenant is not required for this project.

---

## 13. Evaluation

The evaluation suite contains 12 realistic scenarios.

Run the full evaluation in controlled batches.

### First batch

```powershell
python evaluation\evaluate.py --start 0 --limit 3 --reset
```

### Second batch

```powershell
python evaluation\evaluate.py --start 3 --limit 3
```

### Third batch

```powershell
python evaluation\evaluate.py --start 6 --limit 3
```

### Fourth batch

```powershell
python evaluation\evaluate.py --start 9 --limit 3
```

The evaluator accumulates results in:

```text
evaluation/evaluation_results.json
```

The automated evaluator stops at the human approval boundary.

Therefore:

```text
ServiceNow writes = disabled during automated evaluation
```

---

## 14. Final Evaluation Results

The final evaluation was executed using:

```text
Model:
openai/gpt-oss-20b
```

Results:

| Metric | Result |
|---|---:|
| Total scenarios | 12 |
| Passed | 11 |
| Failed | 1 |
| Overall pass rate | **91.7%** |
| Diagnosis accuracy | **100%** |
| Evidence grounding | **90%** |
| Action reasonableness | **100%** |
| Clarification accuracy | **100%** |
| Clarification safety | **100%** |
| Approval safety | **100%** |
| Provider-related failures | **0** |
| Average latency | **22,958.07 ms** |

### Failed case

```text
INC-SIM-007
```

The system correctly diagnosed the search cluster problem, but the diagnosis did not cite the available runbook.

Therefore the case was classified as:

```text
evidence_grounding
```

rather than a diagnosis failure.

This demonstrates that the evaluation separately measures:

```text
Diagnosis correctness
        +
Evidence traceability
```

instead of treating them as the same metric.

See:

```text
evaluation/evaluation_report.md
```

for the detailed evaluation and failure analysis.

---

## 15. Uncertainty and Clarification

The system is designed not to force a diagnosis when evidence is insufficient or contradictory.

### INC-SIM-011

Insufficient evidence caused the workflow to request clarification.

The system produced:

```text
No diagnosis
No remediation
Clarification requested
No ServiceNow write
```

### INC-SIM-012

Conflicting evidence caused the workflow to request clarification instead of choosing an unsupported root cause.

The system produced:

```text
No diagnosis
No remediation
Clarification requested
No ServiceNow write
```

Both scenarios passed the clarification and safety evaluation.

---

## 16. Observability

Each workflow run receives a run ID.

The tracing layer captures information such as:

- Run ID
- Node execution
- Tool calls
- Tool inputs
- Tool outputs
- Redacted sensitive values
- Node latency
- Tool latency
- Errors
- Retry behavior
- Approval state
- Final outcome
- ServiceNow operation information when applicable

Trace files are written locally under:

```text
traces/
```

The directory is excluded from Git because traces may contain operational information.

The implementation is structured so that richer observability systems such as LangSmith can be added later.

---

## 17. Error Handling and Reliability

The application includes bounded retry behavior for transient LLM/provider failures.

Examples include:

```text
Rate-limit retry
Structured-output retry
Transient provider failure
```

Retry attempts are bounded to avoid infinite loops.

Daily-token/quota failures are treated differently from transient rate limits because repeatedly retrying a daily quota failure does not improve the outcome.

Tool failures are represented in workflow state and can route the graph toward retry or clarification.

---

## 18. Duplicate Prevention and Idempotency

ServiceNow writes are treated as potentially repeatable side effects.

The ServiceNow integration therefore includes duplicate-prevention handling.

If a create operation is detected as a duplicate, the workflow does not falsely report that a new incident was created.

Instead, the result records that duplicate creation was prevented.

This distinction is important for operational auditability.

---

## 19. Testing

The project includes graph-level tests covering:

### Normal incident

A normal incident should progress through diagnosis and remediation planning and stop at the approval boundary.

### Insufficient evidence

An insufficient-context incident should request clarification without producing a diagnosis or remediation plan.

### Conflicting evidence

A conflicting-evidence incident should request clarification and should not claim a root cause.

Run:

```powershell
pytest -q
```

Expected result:

```text
3 passed
```

Compilation can be verified with:

```powershell
python -m compileall app evaluation tests
```

---

## 20. Design Decisions

### Why LangGraph?

LangGraph provides explicit workflow state and conditional transitions.

This makes it easier to represent:

- Investigation
- Evidence assessment
- Diagnosis
- Remediation
- Approval
- Clarification
- Retry
- Failure handling

The workflow is therefore deterministic at the orchestration layer even though the LLM is responsible for reasoning.

### Why separate diagnosis and remediation?

Diagnosis answers:

```text
What is most likely happening?
```

Remediation answers:

```text
What should we do about it?
```

Separating them makes validation and safety controls clearer.

### Why structured outputs?

Structured Pydantic models make it possible to validate:

- Required fields
- Confidence range
- Evidence references
- Approval requirements
- ServiceNow fields
- Rollback information

This is safer than relying on free-form LLM text.

### Why human approval?

ServiceNow writes are external side effects.

The LLM can recommend an action, but it should not independently execute an operational change.

Therefore:

```text
LLM recommendation
        |
        v
Human approval
        |
        v
ServiceNow write
```

---

## 21. Production Gaps

This is a take-home V1 rather than a production SRE platform.

A production deployment would require:

### Real observability integrations

Replace simulated data with controlled integrations for:

- Logs
- Metrics
- Traces
- Deployment events
- Dependency health

### Production retrieval

Use a proper retrieval system for:

- Runbooks
- Historical incidents
- Service ownership
- Architecture documentation

### Security

Use:

- Managed secrets
- Short-lived credentials
- Least-privilege ServiceNow accounts
- Role-based authorization
- Audit controls

### Approval controls

Production approval should capture:

- Approver identity
- Timestamp
- Proposed action
- Risk
- Rollback plan
- Authorization policy

### Reliability

Additional controls should include:

- Timeouts
- Circuit breakers
- Provider fallback
- Rate-limit management
- Better latency optimization
- Distributed tracing
- Metrics dashboards

---

## 22. Known Limitations

The current project intentionally uses:

- Simulated logs
- Simulated metrics
- Simulated runbooks
- Simulated historical incidents
- ServiceNow PDI instead of an enterprise production instance

The system does not automatically execute arbitrary infrastructure remediation.

The take-home focuses on demonstrating:

```text
Agentic reasoning
+
Tool use
+
Workflow orchestration
+
Safety
+
Human approval
+
ServiceNow integration
+
Observability
+
Evaluation
```

---

## 23. Future Improvements

With additional development time, the system could be extended with:

- MCP-based tool servers
- LangSmith tracing
- Real observability integrations
- RAG for runbooks and incident history
- Multi-model evaluation
- Confidence-based escalation
- Streaming operator UI
- Role-based approval policies
- Cost tracking
- Kubernetes remediation tools
- Automated postmortem generation
- CI/CD evaluation gates

---

## 24. Interview / Design Summary

The core design can be summarized as:

```text
Investigate
    ↓
Collect evidence
    ↓
Assess evidence quality
    ↓
 ┌──────────────────────────────┐
 │                              │
Insufficient                 Sufficient
 │                              │
 ↓                              ↓
Clarify                     Diagnose
                               ↓
                         Remediation
                               ↓
                         Human Approval
                          /           \
                       Reject        Approve
                         |             |
                         ↓             ↓
                    Clarify       ServiceNow
                                      ↓
                                Final Outcome
```

The key principle is:

> The LLM performs reasoning and recommendation, while the workflow controls state, validation, branching, approval, and external side effects.

---

## 25. Final Status

| Area | Status |
|---|---|
| Project scaffold | Complete |
| Simulated incident data | Complete |
| Typed investigation tools | Complete |
| Typed ServiceNow tools | Complete |
| LangGraph workflow | Complete |
| Evidence assessment | Complete |
| Diagnosis agent | Complete |
| Remediation agent | Complete |
| Human approval | Complete |
| ServiceNow PDI integration | Complete |
| Duplicate prevention | Complete |
| Retry/error handling | Complete |
| Observability | Complete |
| Evaluation harness | Complete |
| 12 scenario evaluation | Complete |
| Evaluation report | Complete |
| Automated tests | Passing |
| Documentation | Complete |



