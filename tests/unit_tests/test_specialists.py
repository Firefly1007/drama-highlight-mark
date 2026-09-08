"""五类 Specialist 的 Agent 执行契约测试。"""

from __future__ import annotations

from typing import Any

import pytest
from langchain.agents.structured_output import ToolStrategy
from langgraph.graph.state import CompiledStateGraph

import drama_interaction.specialists.base as base_module
from drama_interaction.config import Settings
from drama_interaction.context import DramaContext
from drama_interaction.evidence.service import EvidenceService
from drama_interaction.llm import LLMGateway, LLMNetworkExhaustedError
from drama_interaction.schemas.candidate import (
    Abstention,
    Candidate,
    SpecialistResult,
)
from drama_interaction.schemas.evidence import EvidenceDocument, TranscriptSegment
from drama_interaction.specialists import (
    DeferredVoteSpecialist,
    EmotionButtonSpecialist,
    InstantVoteSpecialist,
    RepeatKeylineSpecialist,
    SideCommentSpecialist,
)

TIMELINE = "[T1] 00:00.000-00:02.000 台词：你必须做出选择。"
DRAMA_CONTEXT = DramaContext(
    name="测试剧",
    description="测试简介",
    characters=["甲", "乙"],
)


class FakeAgent:
    """返回预置 LangGraph 状态的已编译 Agent 替身。"""

    def __init__(self, response: object) -> None:
        self.response = response
        self.inputs: list[object] = []

    def invoke(self, input: object) -> object:
        """记录 Agent 输入并返回状态。"""
        self.inputs.append(input)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class FakeGateway:
    """只实现 Specialist 所需的模型和 Agent 网关接口。"""

    model = object()

    def __init__(self) -> None:
        self.calls: list[tuple[object, object, str]] = []

    def invoke_agent(self, agent: FakeAgent, input: object, *, call_label: str) -> object:
        """转发到 Agent，记录调用标签。"""
        self.calls.append((agent, input, call_label))
        return agent.invoke(input)


def _evidence_service() -> EvidenceService:
    """构造最小共享证据文档。"""
    document = EvidenceDocument(
        episode_duration_ms=2000,
        transcript_segments=[
            TranscriptSegment(
                id="T1",
                start_ms=0,
                end_ms=2000,
                text="你必须做出选择。",
            )
        ],
    )
    return EvidenceService(document)


def test_specialist_agent_is_compiled_react_graph() -> None:
    settings = Settings(
        llm_model_id="test-model",
        llm_api_key="test-key",
        llm_base_url="https://example.invalid/v1",
        checkpoint_database_url="postgresql://test:test@localhost/test",
        audio_separator_access_key_id="test-id",
        audio_separator_access_key_secret="test-secret",
        audio_separator_bucket="test-bucket",
        audio_separator_region="ap-guangzhou",
        asr_model_id="qwen-audio-3.0-asr-flash-filetrans",
        asr_api_key="test-key",
        asr_base_url="https://dashscope.aliyuncs.com/api/v1",
        audio_observer_model_id="qwen3-omni-flash",
        audio_observer_api_key="test-key",
        audio_observer_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ocr_model_id="qwen-3.8-flash",
        ocr_api_key="test-key",
        ocr_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        vlm_model_id="qwen-3.8-flash",
        vlm_api_key="test-key",
        vlm_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    specialist = InstantVoteSpecialist(
        gateway=LLMGateway(settings, model=object()),
        drama_context=DRAMA_CONTEXT,
        evidence_service=_evidence_service(),
    )

    assert isinstance(specialist.agent, CompiledStateGraph)
    graph = specialist.agent.get_graph(xray=1)
    assert {"model", "tools"} <= graph.nodes.keys()
    assert {("model", "tools"), ("tools", "model")} <= {
        (edge.source, edge.target) for edge in graph.edges
    }


def _instant_candidate() -> Candidate:
    """构造一条合法的即时投票候选。"""
    return Candidate.model_validate(
        {
            "specialist_type": "instant_vote",
            "evidence_ids": ["T1"],
            "trigger_anchor": {"transcript_segment_id": "T1"},
            "payload": {"question": "你站谁？", "options": ["甲", "乙"]},
        }
    )


def _patch_agent(monkeypatch: pytest.MonkeyPatch, response: object) -> dict[str, Any]:
    """替换 Agent 工厂，保留创建参数供断言。"""
    created: dict[str, Any] = {}

    def create_agent(**kwargs: Any) -> FakeAgent:
        created.update(kwargs)
        agent = FakeAgent(response)
        created["agent"] = agent
        return agent

    monkeypatch.setattr(base_module, "create_agent", create_agent)
    return created


def test_specialist_uses_tool_strategy_and_passes_branch_timeline(monkeypatch):
    result = SpecialistResult(
        specialist_type="instant_vote",
        candidates=[_instant_candidate()],
    )
    created = _patch_agent(
        monkeypatch,
        {"messages": [], "structured_response": result},
    )
    gateway = FakeGateway()
    specialist = InstantVoteSpecialist(
        gateway=gateway,
        drama_context=DRAMA_CONTEXT,
        evidence_service=_evidence_service(),
    )

    output = specialist.run(TIMELINE)

    assert output == result
    assert isinstance(created["response_format"], ToolStrategy)
    assert created["response_format"].schema is SpecialistResult
    assert [tool.name for tool in created["tools"]] == ["inspect_span"]
    assert gateway.calls[0][2] == "specialist:instant_vote"
    prompt = gateway.calls[0][1]["messages"][0]["content"]
    assert TIMELINE in prompt
    assert "测试简介" in prompt
    assert '"characters":["甲","乙"]' in prompt
    assert "两个选项必须立场明确、方向相反" in created["system_prompt"]
    assert "不要提供中立选项" in created["system_prompt"]
    assert "{{PAYLOAD_JSON_SCHEMA}}" not in created["system_prompt"]
    assert "JSON Schema" not in created["system_prompt"]


def test_inspect_span_tool_is_bound_to_the_current_branch(monkeypatch):
    created = _patch_agent(
        monkeypatch,
        {
            "messages": [],
            "structured_response": SpecialistResult(specialist_type="side_comment"),
        },
    )
    SideCommentSpecialist(
        gateway=FakeGateway(),
        drama_context=DRAMA_CONTEXT,
        evidence_service=_evidence_service(),
    )

    output = created["tools"][0].invoke(
        {"start_ms": 0, "end_ms": 1000, "query": "画面发生了什么？"}
    )

    assert "视频观察不可用" in output


def test_specialist_accepts_structured_abstention(monkeypatch):
    result = SpecialistResult(
        specialist_type="side_comment",
        abstentions=[Abstention(specialist_type="side_comment", reason="证据不足")],
    )
    _patch_agent(monkeypatch, {"structured_response": result, "messages": []})
    specialist = SideCommentSpecialist(
        gateway=FakeGateway(),
        drama_context=DRAMA_CONTEXT,
        evidence_service=_evidence_service(),
    )

    output = specialist.run(TIMELINE)

    assert output.candidates == []
    assert output.abstentions[0].reason == "证据不足"


def test_specialist_abstains_when_tool_strategy_result_is_missing(monkeypatch):
    raw_response = {"messages": []}
    _patch_agent(monkeypatch, raw_response)
    specialist = InstantVoteSpecialist(
        gateway=FakeGateway(),
        drama_context=DRAMA_CONTEXT,
        evidence_service=_evidence_service(),
    )

    output = specialist.run(TIMELINE)

    assert output.candidates == []
    assert "结构化输出无效" in output.abstentions[0].reason
    assert specialist.last_raw_response == raw_response


def test_specialist_rejects_evidence_not_visible_in_current_timeline(monkeypatch):
    candidate = Candidate.model_validate(
        {
            "specialist_type": "instant_vote",
            "evidence_ids": ["D9"],
            "trigger_anchor": {"observation_id": "D9"},
            "payload": {"question": "你站谁？", "options": ["甲", "乙"]},
        }
    )
    result = SpecialistResult(
        specialist_type="instant_vote",
        candidates=[candidate],
    )
    _patch_agent(monkeypatch, {"structured_response": result, "messages": []})
    specialist = InstantVoteSpecialist(
        gateway=FakeGateway(),
        drama_context=DRAMA_CONTEXT,
        evidence_service=_evidence_service(),
    )

    output = specialist.run(TIMELINE)

    assert output.candidates == []
    assert "时间线" in output.abstentions[0].reason


def test_deferred_vote_keeps_generation_payload_without_absolute_times(monkeypatch):
    candidate = Candidate.model_validate(
        {
            "specialist_type": "deferred_vote",
            "evidence_ids": ["T1"],
            "trigger_anchor": {"transcript_segment_id": "T1"},
            "reveal_anchor": {"transcript_segment_id": "T1"},
            "payload": {
                "question": "后来会怎样？",
                "options": ["甲", "乙"],
                "answer_id": 0,
            },
        }
    )
    _patch_agent(
        monkeypatch,
        {
            "structured_response": SpecialistResult(
                specialist_type="deferred_vote",
                candidates=[candidate],
            ),
            "messages": [],
        },
    )
    specialist = DeferredVoteSpecialist(
        gateway=FakeGateway(),
        drama_context=DRAMA_CONTEXT,
        evidence_service=_evidence_service(),
    )

    output = specialist.run(TIMELINE)

    assert output.candidates[0].payload.answer_id == 0
    assert output.candidates[0].payload.reveal_time is None
    assert output.candidates[0].payload.reveal_delay is None


def test_regenerate_one_returns_one_structured_candidate(monkeypatch):
    replacement = _instant_candidate()
    gateway = FakeGateway()
    _patch_agent(
        monkeypatch,
        {
            "structured_response": SpecialistResult(
                specialist_type="instant_vote",
                candidates=[replacement],
            ),
            "messages": [],
        },
    )
    specialist = InstantVoteSpecialist(
        gateway=gateway,
        drama_context=DRAMA_CONTEXT,
        evidence_service=_evidence_service(),
    )

    output = specialist.regenerate_one(
        _instant_candidate(),
        errors=[],
        evidence_timeline=TIMELINE,
    )

    assert output == replacement
    assert gateway.calls[0][2] == "specialist:instant_vote:regenerate"
    assert "只能提交一条" in gateway.calls[0][1]["messages"][0]["content"]


@pytest.mark.parametrize(
    ("specialist_cls", "specialist_type"),
    [
        (EmotionButtonSpecialist, "emotion_button"),
        (RepeatKeylineSpecialist, "repeat_keyline"),
        (InstantVoteSpecialist, "instant_vote"),
        (DeferredVoteSpecialist, "deferred_vote"),
        (SideCommentSpecialist, "side_comment"),
    ],
)
def test_concrete_specialists_expose_string_type(specialist_cls, specialist_type):
    assert specialist_cls.specialist_type == specialist_type


def test_network_exhausted_error_is_re_raised_unchanged(monkeypatch):
    network_error = LLMNetworkExhaustedError(
        call_label="specialist:instant_vote",
        model="test-model",
        attempts=2,
        original_error=ConnectionError("down"),
    )
    _patch_agent(monkeypatch, {"messages": []})

    class NetworkGateway(FakeGateway):
        def invoke_agent(self, agent, input, *, call_label):
            raise network_error

    specialist = InstantVoteSpecialist(
        gateway=NetworkGateway(),
        drama_context=DRAMA_CONTEXT,
        evidence_service=_evidence_service(),
    )

    with pytest.raises(LLMNetworkExhaustedError) as raised:
        specialist.run(TIMELINE)

    assert raised.value is network_error
