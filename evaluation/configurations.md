# Evaluation Configuration Comparison

## Purpose

The Incident Copilot was evaluated using two configurations to measure
the effect of bounded LLM resilience.

Both configurations use the same:

- simulated incident dataset
- LangGraph workflow
- investigation tools
- diagnosis schema
- remediation schema
- evaluation criteria

The primary difference is how transient LLM failures are handled.

---

## Configuration A — Baseline Single-Pass

### Behavior

Each diagnosis/remediation LLM operation is attempted once.

If the model returns a transient error or invalid structured output,
the workflow records the failure and continues through its existing
failure/clarification path.

### Characteristics

- Single model invocation
- No retry
- Lower potential latency
- Simpler execution behavior
- More sensitive to transient provider failures

### Expected benefit

Lower latency when the first request succeeds.

### Expected weakness

A temporary rate limit or structured-output failure can cause an
otherwise valid incident investigation to fail.

---

## Configuration B — Bounded Resilient Execution

### Behavior

The current implementation uses bounded retry and quota-aware handling.

Transient rate-limit failures may be retried using exponential backoff.

Structured-output failures may receive a bounded strict-JSON retry.

Daily token quota failures are detected and fail fast rather than
repeatedly retrying a condition that cannot succeed immediately.

### Characteristics

- Bounded retries
- Exponential backoff
- Structured-output recovery
- Daily quota detection
- No unbounded retry loop
- Provider failures remain visible in evaluation results

### Expected benefit

Improved resilience against transient provider failures.

### Expected weakness

Retries can increase latency and cannot solve hard provider quota
exhaustion.

---

## Comparison

| Dimension | Configuration A | Configuration B |
|---|---|---|
| LLM attempts | Single pass | Bounded retry |
| Transient rate-limit handling | Fail | Retry |
| Structured-output recovery | Fail | Bounded retry |
| Daily quota handling | Fail | Fail fast |
| Retry loop | None | Bounded |
| Latency | Lower when successful | Potentially higher |
| Resilience | Lower | Higher |
| Safety | Same approval boundary | Same approval boundary |
| ServiceNow writes during evaluation | Never | Never |

---

## Evaluation interpretation

The evaluation must not hide provider failures.

Provider failures such as daily token quota exhaustion are reported
separately from diagnosis or remediation-quality failures.

A failed case caused by provider quota exhaustion is still visible in
the raw evaluation results, but it should not be interpreted as proof
that the diagnosis logic itself was incorrect.

Final evaluation reporting should therefore include:

1. Raw overall pass rate.
2. Diagnosis accuracy.
3. Evidence grounding.
4. Remediation action reasonableness.
5. Clarification accuracy.
6. Clarification safety.
7. Approval safety.
8. Average latency.
9. Provider failure count.
10. Failure categories.

---

## Production implication

For production deployment, bounded retries should remain enabled, but
with:

- strict retry limits
- exponential backoff
- provider-specific error classification
- request/token budgets
- timeout controls
- observability for retry counts
- circuit breaking where appropriate
- fallback model/provider where justified

The approval boundary remains mandatory regardless of the LLM
configuration.