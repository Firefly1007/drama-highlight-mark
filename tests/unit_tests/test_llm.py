"""LLM 网关 Agent 调用、重试和审计测试。"""

from types import SimpleNamespace

import pytest

from drama_interaction.config import Settings
from drama_interaction.llm import (
    LLMGateway,
    LLMGatewayError,
    LLMNetworkExhaustedError,
)


def _settings(**overrides) -> Settings:
    """构造测试配置。"""

    values = {
        "llm_model_id": "test-model",
        "llm_api_key": "test-key",
        "llm_base_url": "https://llm.example/v1",
        "checkpoint_database_url": "postgresql://user:pass@localhost/db",
        "llm_max_retries": 2,
        "llm_retry_delay_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


class FakeModel:
    """只实现 LangChain 模型的最小调用面。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        """记录 LangChain 消息并返回预设结果。"""

        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeAgent:
    """只实现 LangGraph Agent 的同步调用面。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, input):
        """记录 Agent 状态输入并返回预置结果。"""
        self.calls.append(input)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(content, usage_metadata=None):
    """构造最小 LangChain 模型响应。"""

    return SimpleNamespace(content=content, usage_metadata=usage_metadata)


def _agent_state(usage_metadata=None):
    """构造最小 LangGraph Agent 状态。"""
    return {
        "messages": [_response("agent result", usage_metadata)],
        "structured_response": {"ok": True},
    }


def test_invoke_agent_returns_state_and_audits_model_usage():
    agent = FakeAgent(
        [_agent_state({"input_tokens": 4, "output_tokens": 6, "total_tokens": 10})]
    )
    gateway = LLMGateway(_settings(), model=FakeModel([]))

    state = gateway.invoke_agent(agent, {"messages": [{"role": "user", "content": "go"}]}, "agent.run")

    assert state["structured_response"] == {"ok": True}
    assert agent.calls == [{"messages": [{"role": "user", "content": "go"}]}]
    audit = gateway.last_audit
    assert audit is not None
    assert audit.call_label == "agent.run"
    assert audit.success is True
    assert audit.attempts == 1
    assert audit.prompt_tokens == 4
    assert audit.completion_tokens == 6
    assert audit.total_tokens == 10


def test_invoke_agent_retries_transient_error_then_succeeds():
    sleeps = []
    agent = FakeAgent([TimeoutError("temporary"), _agent_state()])
    gateway = LLMGateway(
        _settings(llm_max_retries=1, llm_retry_delay_seconds=0.25),
        model=FakeModel([]),
        sleep_fn=sleeps.append,
    )

    gateway.invoke_agent(agent, {"messages": []}, "agent.retry")

    assert len(agent.calls) == 2
    assert sleeps == [0.25]
    assert gateway.last_audit is not None
    assert gateway.last_audit.attempts == 2


def test_invoke_agent_network_exhaustion_is_audited():
    agent = FakeAgent([ConnectionError("down"), ConnectionError("still down")])
    gateway = LLMGateway(_settings(llm_max_retries=1), model=FakeModel([]))

    with pytest.raises(LLMNetworkExhaustedError) as error:
        gateway.invoke_agent(agent, {"messages": []}, "agent.network")

    assert error.value.call_label == "agent.network"
    assert error.value.attempts == 2
    assert gateway.last_audit is not None
    assert gateway.last_audit.error_type == "network_exhausted"


def test_invoke_agent_wraps_non_network_error_without_retry():
    agent = FakeAgent([ValueError("bad request")])
    gateway = LLMGateway(_settings(), model=FakeModel([]))

    with pytest.raises(LLMGatewayError, match="bad request"):
        gateway.invoke_agent(agent, {"messages": []}, "agent.bad")

    assert len(agent.calls) == 1
    assert gateway.last_audit is not None
    assert gateway.last_audit.success is False
