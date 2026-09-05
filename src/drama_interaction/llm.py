"""唯一 LLM 网络出口：调用、有限重试与审计。"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from langchain_core.exceptions import (
    ModelConnectionError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from langchain_openai import ChatOpenAI

from drama_interaction.config import Settings


class LLMGatewayError(RuntimeError):
    """LLM 网关错误基类。"""


class LLMNetworkExhaustedError(LLMGatewayError):
    """瞬时网络错误在有限重试后仍未恢复。"""

    category = "network_exhausted"

    def __init__(
        self,
        *,
        call_label: str,
        model: str,
        attempts: int,
        original_error: Exception,
    ) -> None:
        self.call_label = call_label
        self.model = model
        self.attempts = attempts
        self.original_error = original_error
        super().__init__(
            f"LLM 网络调用耗尽重试: label={call_label!r}, model={model!r}, "
            f"attempts={attempts}, error={original_error}"
        )


@dataclass(frozen=True, slots=True)
class LLMCallAudit:
    """一次网关调用的最小审计记录。"""

    call_label: str
    model: str
    elapsed_ms: float
    success: bool
    attempts: int = 1
    usage: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    error_type: str | None = None
    error_message: str | None = None


def _extract_usage(response: Any) -> tuple[Mapping[str, Any], int | None, int | None, int | None]:
    """保留 LangChain 标准 usage_metadata。"""
    raw_usage = getattr(response, "usage_metadata", None)
    if not isinstance(raw_usage, Mapping):
        return MappingProxyType({}), None, None, None

    usage = dict(raw_usage)
    prompt_tokens = usage.get("input_tokens")
    completion_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    return MappingProxyType(usage), prompt_tokens, completion_tokens, total_tokens


def _extract_agent_usage(
    response: Any,
) -> tuple[Mapping[str, Any], int | None, int | None, int | None]:
    """从 Agent 状态中读取最后一条模型消息的用量。"""
    if isinstance(response, Mapping):
        messages = response.get("messages", ())
        for message in reversed(messages):
            usage = _extract_usage(message)
            if usage[0]:
                return usage
    return _extract_usage(response)


def _is_retryable(error: Exception) -> bool:
    """判断是否属于网关负责的瞬时网络错误。"""

    return isinstance(
        error,
        (
            ModelConnectionError,
            ModelRateLimitError,
            ModelTimeoutError,
            ConnectionError,
            TimeoutError,
        ),
    )


class LLMGateway:
    """封装 LangChain ChatOpenAI 的同步模型网关。"""

    def __init__(
        self,
        settings: Settings,
        *,
        model: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.model = (
            ChatOpenAI(
                model=settings.llm_model_id,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                temperature=settings.llm_temperature,
                timeout=settings.llm_timeout_seconds,
                max_tokens=settings.llm_max_tokens,
                max_retries=0,
                use_responses_api=False,
            )
            if model is None
            else model
        )
        self._sleep = sleep_fn
        self._max_retries = settings.llm_max_retries
        self._retry_delay_seconds = settings.llm_retry_delay_seconds
        self.audit_records: list[LLMCallAudit] = []

    @property
    def last_audit(self) -> LLMCallAudit | None:
        """返回最近一条审计记录。"""

        return self.audit_records[-1] if self.audit_records else None

    def _invoke(
        self,
        operation: Callable[[], Any],
        *,
        call_label: str,
    ) -> Any:
        """执行一次可重试调用并记录一条审计。"""
        selected_model = self.settings.llm_model_id
        started = time.perf_counter()
        attempts = 0
        while True:
            attempts += 1
            try:
                response = operation()
            except Exception as error:
                retryable = _is_retryable(error)
                if retryable and attempts <= self._max_retries:
                    if self._retry_delay_seconds:
                        self._sleep(self._retry_delay_seconds)
                    continue
                elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000)
                self.audit_records.append(
                    LLMCallAudit(
                        call_label=call_label,
                        model=selected_model,
                        elapsed_ms=elapsed_ms,
                        success=False,
                        attempts=attempts,
                        error_type=(
                            "network_exhausted"
                            if retryable
                            else type(error).__name__
                        ),
                        error_message=str(error),
                    )
                )
                if retryable:
                    raise LLMNetworkExhaustedError(
                        call_label=call_label,
                        model=selected_model,
                        attempts=attempts,
                        original_error=error,
                    ) from error
                raise LLMGatewayError(
                    f"LLM 调用失败: label={call_label!r}, model={selected_model!r}, "
                    f"error={error}"
                ) from error

            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000)
            usage, prompt_tokens, completion_tokens, total_tokens = _extract_agent_usage(
                response
            )
            self.audit_records.append(
                LLMCallAudit(
                    call_label=call_label,
                    model=selected_model,
                    elapsed_ms=elapsed_ms,
                    success=True,
                    attempts=attempts,
                    usage=usage,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
            )
            return response

    def invoke_agent(
        self,
        agent: Any,
        input: Any,
        call_label: str,
    ) -> Any:
        """调用 LangGraph Agent，并统一处理网络重试与审计。"""
        return self._invoke(
            lambda: agent.invoke(input),
            call_label=call_label,
        )

__all__ = [
    "LLMCallAudit",
    "LLMGateway",
    "LLMGatewayError",
    "LLMNetworkExhaustedError",
]
