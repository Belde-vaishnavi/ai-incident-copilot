# AI Incident Copilot

AI Incident Copilot is a lightweight, production-minded incident investigation assistant for SRE workflows.

The system accepts an incident description, collects relevant evidence from simulated logs, metrics, runbooks, and historical incident context, reasons about a likely root cause, produces a structured remediation plan, and requires explicit human approval before creating or updating an incident in a ServiceNow Personal Developer Instance (PDI).

This project is being built as a structured agentic workflow rather than a simple chatbot.

## Goals

- Investigate an incident using multiple typed tools.
- Keep workflow state explicit and traceable.
- Ground the diagnosis in collected evidence.
- Produce a valid structured remediation plan.
- Require human approval before every ServiceNow write.
- Safely create or update ServiceNow incidents in a PDI.
- Capture workflow and tool execution for observability.
- Evaluate the system against repeatable incident scenarios.

## Assignment Scope

The implementation follows the take-home assignment requirements:

1. Accept an incident description.
2. Fetch or simulate relevant logs and metrics.
3. Consult simulated runbooks and historical incident context.
4. Diagnose a likely root cause with confidence.
5. Produce a structured remediation plan.
6. Ask for human approval.
7. If approved, create or update a ServiceNow incident.
8. If rejected, revise the plan or ask for clarification.
9. Record enough trace information to explain the workflow.

## Architecture

The project uses an explicit LangGraph `StateGraph` workflow with typed/shared state.

```text
SRE / User
    |
    v
Incident Input
    |
    v
LangGraph State
    |
    +--> Fetch Logs
    +--> Fetch Metrics
    +--> Search Runbooks
    +--> Search Historical Incidents
             |
             v
       Evidence Analysis
             |
             v
      Context Sufficient?
         /          \
       No            Yes
       |              |
       v              v
Ask Clarification  Diagnosis + Confidence
                       |
                       v
                Remediation Plan
                       |
                       v
                 Human Approval
                   /          \
               Reject        Approve
                 |              |
                 v              v
           Revise/Clarify   ServiceNow
                                |
                                v
                         Final Outcome
                                |
                                v
                         Observability
```

## Design Principles

- **Explicit state:** workflow data is represented in a typed state object.
- **Single responsibility:** each graph node performs one clear responsibility.
- **Deterministic orchestration:** LangGraph controls workflow transitions and branching.
- **LLM reasoning behind a provider/configuration layer:** model selection is configuration-driven rather than hard-coded into workflow logic.
- **Typed tools:** tools have narrow input/output schemas.
- **Evidence grounding:** the model receives structured tool results rather than an unstructured dump of all data.
- **Approval boundary:** ServiceNow side effects cannot execute without human approval.
- **Validation and retry:** structured model output is validated before it is accepted.
- **Auditability:** workflow runs, node execution, tool calls, latency, and final outcomes are recorded.

## Project Structure

The project is organized as a modular agentic application. LangGraph is responsible for workflow orchestration, while agents, tools, schemas, prompts, simulated data, and evaluation are kept as separate components.

```text
ServiceNow-Incident-Copilot/
│
├── app/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── incident_investigation_agent.py
│   │   ├── diagnosis_agent.py
│   │   └── remediation_agent.py
│   │
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py
│   │   ├── nodes.py
│   │   ├── edges.py
│   │   └── graph_builder.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── incident.py
│   │   ├── investigation.py
│   │   └── remediation.py
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── runbook_tools.py
│   │   ├── log_tools.py
│   │   ├── metric_tools.py
│   │   └── servicenow_tools.py
│   │
│   ├── data/
│   │   ├── runbooks.json
│   │   ├── logs.json
│   │   ├── metrics.json
│   │   └── historical_incidents.json
│   │
│   ├── prompts/
│   │   ├── diagnosis_prompt.py
│   │   └── remediation_prompt.py
│   │
│   ├── main.py
│   └── __init__.py
│
├── evaluation/
│   ├── incidents.json
│   ├── evaluate.py
│   └── evaluation_report.md
│
├── docs/
│   ├── architecture.md
│   └── design_notes.md
│
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

The structure will be created incrementally as each implementation phase is completed.

## Workflow

The workflow will be implemented incrementally.

### 1. Incident Input

The system receives:

- Incident description
- Service
- Severity
- Investigation time window

### 2. Context Collection

The workflow uses typed tools to collect:

- Logs
- Metrics
- Runbook matches
- Historical incident matches

### 3. Evidence Analysis

The collected results are normalized into structured evidence.

The workflow should distinguish:

- Observed evidence
- Historical/runbook context
- LLM inference

### 4. Diagnosis

The LLM produces:

- Incident summary
- Likely root cause
- Confidence
- Evidence references

### 5. Remediation Plan

The output includes:

- Recommended actions
- Risk
- Approval requirement
- Rollback plan
- ServiceNow update content

### 6. Human Approval

The proposed action is presented to the human before any ServiceNow write.

Rejected plans will not execute a ServiceNow write.

The workflow will instead revise the plan or request additional context.

### 7. ServiceNow

After approval, the workflow can:

- Create an incident
- Read incident details
- Update incident state/work notes
- Attach the AI-generated triage/remediation information to work notes

A ServiceNow Personal Developer Instance (PDI) will be used for the assignment. A real company ServiceNow tenant will not be used.

### 8. Final Outcome

The final result will contain:

- Diagnosis
- Confidence
- Evidence
- Proposed action
- Approval status
- ServiceNow execution status
- ServiceNow incident ID when available

## Required Tools

The implementation will provide these typed tools.

### `search_runbooks(query, service, severity)`

Searches simulated runbook and historical incident context.

Expected structured result includes:

- Source ID
- Snippet
- Relevance reasoning

### `fetch_logs(service, start_time, end_time)`

Returns simulated logs containing:

- Timestamps
- Errors
- Request IDs

### `fetch_metrics(service, start_time, end_time)`

Returns simulated metrics containing:

- Latency
- Error rate
- CPU/memory
- Dependency health

### `create_servicenow_incident(title, description, severity, work_notes)`

Creates an incident in the ServiceNow PDI.

This is a side-effecting tool and requires human approval.

### `update_servicenow_incident(incident_id, state, work_notes)`

Updates an incident in the ServiceNow PDI.

This is a side-effecting tool and requires human approval.

## Structured Remediation Output

The remediation plan will be validated as JSON using a typed schema.

Planned shape:

```json
{
  "incident_summary": "string",
  "likely_root_cause": "string",
  "confidence": 0.0,
  "evidence": [
    {
      "source": "logs",
      "detail": "string"
    }
  ],
  "recommended_actions": [
    {
      "action": "string",
      "risk": "low|medium|high",
      "requires_approval": true
    }
  ],
  "rollback_plan": "string",
  "servicenow_update": {
    "short_description": "string",
    "severity": "string",
    "work_notes": "string"
  }
}
```

Invalid structured output will be rejected and handled through the workflow's retry/recovery path.

## Safety Model

ServiceNow writes are treated as side effects.

### Required Protections

- Human approval before every ServiceNow write.
- Input validation.
- Idempotency or duplicate-prevention strategy.
- Structured success/error responses.
- Tool-call logging.
- Sensitive-value redaction.
- Credentials stored only through environment variables.
- No ServiceNow credentials or API keys committed to Git.

### Insufficient Context

The system should not invent a diagnosis when evidence is insufficient.

Instead, it should ask for additional context or clearly report that it cannot safely recommend an action.

## Configuration

LLM and ServiceNow configuration will be environment-driven.

Create a local `.env` file based on `.env.example`.

Example variables:

```env
LLM_PROVIDER=
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
OPENAI_API_VERSION=

SERVICENOW_INSTANCE=
SERVICENOW_USERNAME=
SERVICENOW_PASSWORD=
```

Only `.env.example` is committed to Git. Secrets must never be committed.

## Local Setup

Create the virtual environment:

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure environment variables:

```text
Copy .env.example to .env and fill in the required values.
```

Run the application:

```bash
python -m app.main
```

## Evaluation

At least 10 realistic incident scenarios will be executed.

The evaluation will measure:

1. Diagnosis accuracy
2. Relevant context selection and citation
3. Reasonableness of recommended action
4. ServiceNow create/update success
5. Average latency
6. Failure cases
7. Correct clarification behavior when evidence is insufficient

Two configurations will also be compared.

The initial comparison will use:

- **Configuration A:** single-pass reasoning
- **Configuration B:** reasoning with reflection/retry

The exact configuration and results will be documented after implementation.

## Observability

Each workflow run will have a run ID.

The system will capture, where available:

- Run ID
- Node execution
- Tool inputs/outputs
- Redacted sensitive values
- Step/tool latency
- Model name
- Token usage
- Diagnosis
- Confidence
- ServiceNow incident ID
- Success/failure information

LangSmith may be added after the baseline observability is working.

## Git Development Strategy

The project will be developed incrementally.

Planned commit progression:

```text
1. Project scaffold, README outline, dependency setup
2. Simulated incident, logs, metrics, runbook and historical data
3. Typed tool schemas for context collection and ServiceNow
4. LangGraph workflow with state and branching
5. Human approval gate before ServiceNow writes
6. ServiceNow PDI create/read/update integration
7. Observability/logging/LangSmith tracing
8. Evaluation harness and 10 sample incident results
9. Final documentation, architecture diagram and limitations
```

Commit messages should describe the intent of each change.

## Current Implementation Status

| Area | Status |
|---|---|
| Project scaffold | Complete |
| Simulated data | Not started |
| Typed tools | Not started |
| LangGraph workflow | Not started |
| Structured diagnosis | Not started |
| Human approval | Not started |
| ServiceNow PDI | Not started |
| Observability | Not started |
| Evaluation | Not started |
| Documentation | Initial README |

## Known Limitations

The following areas are intentionally planned as lightweight/mock components for the initial version:

- Incident logs, metrics, runbooks, and historical context are simulated/local data.
- The application is intended as a take-home V1, not a complete production SRE platform.
- Remediation execution outside ServiceNow is not part of the required baseline.
- Production deployment, enterprise authentication/authorization, and full operational infrastructure are outside the initial scope.

Additional limitations will be documented after implementation.

## Stretch Goals

Only after all required functionality works:

- Actual MCP server for ServiceNow and simulated context tools
- LangSmith named traces
- Confidence-based retry or clarification flow
- Multi-model comparison
- Streamlit UI
- Dockerized deployment
- CI checks
- Simulated Kubernetes remediation tool
- Role-based approval policy
- Incident postmortem generator

## Final Design Questions

The final submission will explicitly answer:

1. What part is production-ready?
2. What part is intentionally mocked?
3. What would be improved with one more week?
4. What was the hardest design tradeoff?
5. What are the biggest risks if deployed for real SREs?

## Development Approach

This repository is intentionally developed phase-by-phase.

Each phase will be:

1. Implemented
2. Tested
3. Verified
4. Committed with a descriptive Git message
5. Followed by the next phase

The goal is to demonstrate engineering decisions and incremental development, not only the final output.
