"""
LLM provider and resilient structured-output invocation helpers.

Responsibilities:
1. Create the configured Groq/OpenAI-compatible chat model.
2. Detect transient LLM failures that are safe to retry.
3. Avoid retrying exhausted daily token quotas.
4. Retry structured JSON generation when the provider rejects the
   generated JSON.
5. Keep retry behavior centralized so diagnosis and remediation agents
   use the same policy.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

MAX_TRANSIENT_RETRIES = int(
    os.getenv("LLM_MAX_RETRIES", "2")
)

TRANSIENT_RETRY_BASE_SECONDS = float(
    os.getenv("LLM_RETRY_BASE_SECONDS", "2")
)

STRUCTURED_OUTPUT_RETRY_COUNT = int(
    os.getenv("LLM_STRUCTURED_OUTPUT_RETRIES", "1")
)


# ---------------------------------------------------------------------------
# LLM creation
# ---------------------------------------------------------------------------

def get_llm():
    """
    Create the configured chat model.
    """

    api_key = os.getenv("API_KEY")

    if not api_key:
        raise ValueError(
            "API_KEY environment variable is required."
        )

    model = os.getenv(
        "GROK_MODEL",
        "openai/gpt-oss-120b",
    )

    base_url = os.getenv(
        "GROK_BASE_URL",
        "https://api.groq.com/openai/v1",
    )

    return ChatOpenAI(
        model=model,
        temperature=0,
        api_key=api_key,
        base_url=base_url,
    )


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

def _exception_text(exc: Exception) -> str:
    """
    Convert an exception into normalized searchable text.
    """

    return str(exc).lower()


def _is_daily_token_limit(exc: Exception) -> bool:
    """
    Detect Groq token-per-day exhaustion.

    A TPD exhaustion should NOT be retried because another request will
    consume more quota and cannot succeed until the provider quota resets.
    """

    text = _exception_text(exc)

    return any(
        marker in text
        for marker in (
            "tokens per day",
            "token per day",
            "tpd",
            "daily token",
            "daily quota",
        )
    )


def _is_rate_limit_error(exc: Exception) -> bool:
    """
    Detect HTTP/provider rate-limit errors.
    """

    text = _exception_text(exc)

    return (
        "429" in text
        or "rate limit" in text
        or "rate_limit_exceeded" in text
        or "too many requests" in text
    )


def _is_json_validation_error(exc: Exception) -> bool:
    """
    Detect structured-output JSON validation failures returned by Groq.
    """

    text = _exception_text(exc)

    return any(
        marker in text
        for marker in (
            "json_validate_failed",
            "failed to generate json",
            "failed_generation",
            "invalid_request_error",
        )
    )


def _is_transient_error(exc: Exception) -> bool:
    """
    Return True when an exception is reasonably safe to retry.

    Daily token exhaustion is explicitly excluded.
    """

    if _is_daily_token_limit(exc):
        return False

    return _is_rate_limit_error(exc)


# ---------------------------------------------------------------------------
# Prompt augmentation
# ---------------------------------------------------------------------------

def _structured_retry_prompt(prompt: str) -> str:
    """
    Strengthen the prompt after a provider-side structured JSON failure.
    """

    return f"""
{prompt}

IMPORTANT STRUCTURED OUTPUT REQUIREMENTS:
- Return ONLY the requested structured object.
- Do not return Markdown.
- Do not wrap the object in ```json fences.
- Do not add explanatory text before or after the object.
- Follow the requested schema exactly.
- Every required field must be present.
- All strings must be valid JSON strings.
- Escape newline characters inside JSON string values.
- Do not include unsupported fields.
""".strip()


# ---------------------------------------------------------------------------
# Resilient structured invocation
# ---------------------------------------------------------------------------

def invoke_structured_with_retry(
    structured_llm: Any,
    prompt: str,
    operation_name: str,
    *,
    max_transient_retries: int | None = None,
    structured_output_retries: int | None = None,
) -> Any:
    """
    Invoke a structured-output LLM with bounded resilience.

    Retry policy:

    1. TPM/transient 429:
       Retry with exponential backoff.

    2. TPD/daily token exhaustion:
       Fail immediately.

    3. Provider-side structured JSON validation failure:
       Retry once with a stricter JSON instruction.

    4. Other errors:
       Fail immediately.

    This function deliberately keeps retries bounded so the evaluation
    cannot become stuck waiting for a provider quota that will not recover.
    """

    transient_retries = (
        MAX_TRANSIENT_RETRIES
        if max_transient_retries is None
        else max_transient_retries
    )

    json_retries = (
        STRUCTURED_OUTPUT_RETRY_COUNT
        if structured_output_retries is None
        else structured_output_retries
    )

    transient_attempt = 0
    json_attempt = 0
    current_prompt = prompt

    while True:
        try:
            logger.info(
                "LLM invocation started | operation=%s | "
                "transient_retry=%d/%d | json_retry=%d/%d",
                operation_name,
                transient_attempt,
                transient_retries,
                json_attempt,
                json_retries,
            )

            result = structured_llm.invoke(current_prompt)

            logger.info(
                "LLM invocation succeeded | operation=%s | "
                "transient_retries_used=%d | json_retries_used=%d",
                operation_name,
                transient_attempt,
                json_attempt,
            )

            return result

        except Exception as exc:
            # ---------------------------------------------------------------
            # Daily token quota: fail immediately.
            # ---------------------------------------------------------------

            if _is_daily_token_limit(exc):
                logger.error(
                    "LLM daily token quota exhausted | operation=%s | "
                    "no retry will be attempted | error=%s",
                    operation_name,
                    type(exc).__name__,
                )

                raise

            # ---------------------------------------------------------------
            # Transient rate limit: bounded retry.
            # ---------------------------------------------------------------

            if _is_transient_error(exc):
                if transient_attempt >= transient_retries:
                    logger.error(
                        "LLM transient retry limit exhausted | "
                        "operation=%s | retries=%d | error=%s",
                        operation_name,
                        transient_attempt,
                        type(exc).__name__,
                    )

                    raise

                transient_attempt += 1

                delay = (
                    TRANSIENT_RETRY_BASE_SECONDS
                    * (2 ** (transient_attempt - 1))
                )

                logger.warning(
                    "LLM transient rate limit | operation=%s | "
                    "retry=%d/%d | sleeping=%.2fs | error=%s",
                    operation_name,
                    transient_attempt,
                    transient_retries,
                    delay,
                    type(exc).__name__,
                )

                time.sleep(delay)
                continue

            # ---------------------------------------------------------------
            # Structured JSON validation failure: one controlled retry.
            # ---------------------------------------------------------------

            if _is_json_validation_error(exc):
                if json_attempt >= json_retries:
                    logger.error(
                        "LLM structured-output retry limit exhausted | "
                        "operation=%s | retries=%d | error=%s",
                        operation_name,
                        json_attempt,
                        type(exc).__name__,
                    )

                    raise

                json_attempt += 1

                current_prompt = _structured_retry_prompt(
                    current_prompt
                )

                logger.warning(
                    "LLM structured JSON validation failed | "
                    "operation=%s | retry=%d/%d | error=%s",
                    operation_name,
                    json_attempt,
                    json_retries,
                    type(exc).__name__,
                )

                continue

            # ---------------------------------------------------------------
            # Non-retryable error.
            # ---------------------------------------------------------------

            logger.error(
                "LLM non-retryable error | operation=%s | error=%s",
                operation_name,
                type(exc).__name__,
            )

            raise