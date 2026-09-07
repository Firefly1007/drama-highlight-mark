"""外部 API 调用的统一重试策略。"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError

from drama_interaction.config import MODEL_RETRY_COUNT, MODEL_RETRY_DELAY_SECONDS

# openai 与 httpx 的连接、超时、读写与协议错误；HTTP 状态码另判。
_TRANSPORT_ERRORS = (APIConnectionError, httpx.TransportError)
_API_ERRORS = (APIStatusError, httpx.HTTPStatusError, *_TRANSPORT_ERRORS)


def _is_retryable(error: Exception) -> bool:
    """429 与 5xx 可重试；纯传输层错误可重试；其余 4xx 不可重试。"""
    if isinstance(error, APIStatusError):
        status = error.status_code
    elif isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
    else:
        return True
    return status == 429 or status >= 500


def retry_call(
    operation: Callable[[], Any],
    error_type: type[Exception],
    what: str,
) -> Any:
    """执行调用：网络失败、超时、429 与 5xx 按配置重试。

    鉴权、请求参数与其它 4xx 不重试；重试耗尽与不可重试错误统一转换为
    ``error_type``。

    Args:
        operation: 无参调用。
        error_type: 失败时抛出的领域异常类型。
        what: 错误信息前缀，例如 ``OCR 调用``。

    Returns:
        operation 的返回值。

    Raises:
        Exception: ``error_type`` 的实例。
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            return operation()
        except _API_ERRORS as exc:
            if not _is_retryable(exc):
                raise error_type(f"{what}失败: {exc}") from exc
            if attempts > MODEL_RETRY_COUNT:
                raise error_type(f"{what}重试耗尽: {exc}") from exc
            time.sleep(MODEL_RETRY_DELAY_SECONDS)


__all__ = ["retry_call"]
