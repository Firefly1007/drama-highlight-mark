"""统一外部调用重试策略单元测试。"""

from __future__ import annotations

from unittest.mock import call, patch

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from drama_interaction.config import MODEL_RETRY_COUNT, MODEL_RETRY_DELAY_SECONDS
from drama_interaction.retry import retry_call


class _DomainError(RuntimeError):
    """被转换成的领域异常。"""


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.example/v1/chat/completions")
    return httpx.HTTPStatusError(
        f"status {status}",
        request=request,
        response=httpx.Response(status, request=request),
    )


def _openai_status_error(status: int) -> APIStatusError:
    request = httpx.Request("POST", "https://api.example/v1/chat/completions")
    return APIStatusError(
        f"status {status}", response=httpx.Response(status, request=request), body=None
    )


def _openai_connection_error() -> APIConnectionError:
    return APIConnectionError(
        request=httpx.Request("POST", "https://api.example/v1/chat")
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _openai_status_error(429),
        lambda: _openai_status_error(500),
        lambda: _http_status_error(429),
        lambda: _http_status_error(503),
        _openai_connection_error,
        lambda: httpx.ConnectTimeout("timed out"),
        lambda: httpx.ReadError("connection reset"),
    ],
    ids=[
        "openai-429",
        "openai-500",
        "httpx-429",
        "httpx-503",
        "openai-connection",
        "httpx-timeout",
        "httpx-read-error",
    ],
)
def test_retryable_errors_are_retried_three_times(factory):
    """测试网络失败、超时、429 与 5xx 最多再重试三次，每次等待一秒。"""
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        raise factory()

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(_DomainError, match="重试耗尽"):
            retry_call(operation, _DomainError, "OCR 调用")

    assert attempts == 1 + MODEL_RETRY_COUNT
    assert (
        mock_sleep.call_args_list
        == [call(MODEL_RETRY_DELAY_SECONDS)] * MODEL_RETRY_COUNT
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _openai_status_error(400),
        lambda: _openai_status_error(401),
        lambda: _openai_status_error(404),
        lambda: _http_status_error(400),
    ],
    ids=["openai-400", "openai-401", "openai-404", "httpx-400"],
)
def test_non_retryable_client_errors_fail_at_once(factory):
    """测试鉴权与请求参数类 4xx 不重试，直接转换为领域异常。"""
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        raise factory()

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(_DomainError, match="失败") as caught:
            retry_call(operation, _DomainError, "上传 mix.flac")

    assert attempts == 1
    assert mock_sleep.call_args_list == []
    assert "上传 mix.flac失败" in str(caught.value)


def test_success_after_one_retry_returns_value():
    """测试首次可重试失败、第二次成功时返回结果并只等待一次。"""
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _http_status_error(502)
        return "ok"

    with patch("time.sleep") as mock_sleep:
        assert retry_call(operation, _DomainError, "下载") == "ok"

    assert attempts == 2
    assert mock_sleep.call_args_list == [call(MODEL_RETRY_DELAY_SECONDS)]


def test_other_exceptions_propagate_untouched():
    """测试响应解析等非传输异常既不重试也不被转换。"""
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        raise ValueError("bad json")

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(ValueError, match="bad json"):
            retry_call(operation, _DomainError, "OCR 调用")

    assert attempts == 1
    assert mock_sleep.call_args_list == []


def test_retry_budget_constant():
    """测试重试预算与等待时长保持计划固定的三次一秒。"""
    assert (MODEL_RETRY_COUNT, MODEL_RETRY_DELAY_SECONDS) == (3, 1.0)
