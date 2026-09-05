"""调度核心规则的离线回归测试。"""

import random
from uuid import uuid5

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from drama_interaction.context import DramaContext
from drama_interaction.llm import LLMNetworkExhaustedError
from drama_interaction.scheduling.constraints import (
    PROJECT_NAMESPACE,
    intervals_conflict,
    render_candidate,
)
from drama_interaction.scheduling.semantic import SemanticDecision, select_candidate_ids
from drama_interaction.schemas.candidate import Candidate, RevealAnchor, TriggerAnchor
from drama_interaction.schemas.evidence import EvidenceDocument, TranscriptSegment
from drama_interaction.schemas.interaction import FinalInteraction

DRAMA_CONTEXT = DramaContext(name="测试剧", description="测试简介", characters=["甲"])


def _interaction(identifier: int, show_at: int, duration_ms: int = 1000) -> FinalInteraction:
    """构造测试用即时投票。"""

    return FinalInteraction(
        id=identifier,
        type="instant_vote",
        show_at=show_at,
        duration_ms=duration_ms,
        payload={"question": "你站谁？", "options": ["甲", "乙"]},
    )


def test_intervals_use_half_open_overlap_rule():
    """相邻端点不冲突，任何实际相交都冲突。"""

    assert not intervals_conflict(_interaction(1, 0), _interaction(2, 1000))
    assert intervals_conflict(_interaction(1, 0), _interaction(2, 999))


def test_deferred_vote_uuid5_shuffle_is_repeatable_and_remaps_answer():
    """相同 execution/candidate 输入必须得到相同选项顺序和答案索引。"""

    document = EvidenceDocument(
        episode_duration_ms=20_000,
        transcript_segments=[
            TranscriptSegment(id="T1", start_ms=0, end_ms=1000, text="开始"),
            TranscriptSegment(id="T2", start_ms=10_000, end_ms=11_000, text="揭晓"),
        ],
    )
    candidate = Candidate(
        candidate_id="c1",
        specialist_type="deferred_vote",
        evidence_ids=["T1", "T2"],
        trigger_anchor=TriggerAnchor(transcript_segment_id="T1"),
        reveal_anchor=RevealAnchor(transcript_segment_id="T2"),
        payload={
            "question": "谁会先到？",
            "options": ["甲", "乙", "丙"],
            "answer_id": 0,
        },
    )

    first = render_candidate(candidate, document, execution_id="run-1")
    second = render_candidate(candidate, document, execution_id="run-1")
    assert first.payload == second.payload

    indices = [0, 1, 2]
    random.Random(uuid5(PROJECT_NAMESPACE, "run-1:c1").int).shuffle(indices)
    expected_options = ["甲", "乙", "丙"]
    assert first.payload.options == [expected_options[i] for i in indices]
    assert first.payload.answer_id == indices.index(0)


class _FakeGateway:
    """记录 Agent 调用并返回预置结构化结果的假网关。"""

    model = FakeListChatModel(responses=["unused"])

    def __init__(self, response: SemanticDecision) -> None:
        self.response = response
        self.calls: list[tuple[object, object, str]] = []

    def invoke_agent(self, agent: object, payload: object, *, call_label: str) -> object:
        self.calls.append((agent, payload, call_label))
        return {"structured_response": self.response}


def test_semantic_scheduler_accepts_only_existing_candidate_id():
    """真实冲突调用模型，并接受现有候选 ID。"""

    gateway = _FakeGateway(
        SemanticDecision(selected_candidate_ids=["c2"], reason="覆盖更晚互动")
    )
    result = select_candidate_ids(
        gateway,
        {"c1": _interaction(1, 0), "c2": _interaction(2, 500)},
        [("c1", "c2")],
        {"c1": "[T1] 证据甲", "c2": "[T2] 证据乙"},
        DRAMA_CONTEXT,
    )

    assert result.status == "selected"
    assert result.selected_candidate_ids == ["c2"]
    assert len(gateway.calls) == 1
    assert "测试简介" in gateway.calls[0][1]["messages"][0]["content"]


def test_semantic_scheduler_routes_illegal_selection_to_hitl():
    """模型返回未知 ID 时保留原响应并交给人工。"""

    response = SemanticDecision(selected_candidate_ids=["invented"])
    gateway = _FakeGateway(response)
    result = select_candidate_ids(
        gateway,
        {"c1": _interaction(1, 0), "c2": _interaction(2, 500)},
        [("c1", "c2")],
        {"c1": "[T1] 证据甲", "c2": "[T2] 证据乙"},
        DRAMA_CONTEXT,
    )

    assert result.requires_human
    assert result.status == "waiting_for_human"
    assert result.raw_response == {"structured_response": response}


def test_semantic_scheduler_skips_gateway_without_real_conflict():
    """确定性可解时不产生 LLM 调用。"""

    gateway = _FakeGateway(SemanticDecision(selected_candidate_ids=["never"]))
    result = select_candidate_ids(
        gateway,
        {"c1": _interaction(1, 0), "c2": _interaction(2, 1000)},
        [("c1", "c2")],
        {"c1": "[T1] 证据甲", "c2": "[T2] 证据乙"},
        DRAMA_CONTEXT,
    )

    assert result.status == "deterministic"
    assert result.selected_candidate_ids == ["c1", "c2"]
    assert gateway.calls == []


def test_semantic_scheduler_routes_network_exhaustion_to_hitl():
    """网关耗尽网络重试时不得静默选择或回退。"""

    class _ExhaustedGateway(_FakeGateway):
        def invoke_agent(self, agent: object, payload: object, *, call_label: str) -> object:
            raise LLMNetworkExhaustedError(
                call_label=call_label,
                model="test-model",
                attempts=2,
                original_error=ConnectionError("down"),
            )

    result = select_candidate_ids(
        _ExhaustedGateway(None),
        {"c1": _interaction(1, 0), "c2": _interaction(2, 500)},
        [("c1", "c2")],
        {"c1": "[T1] 证据甲", "c2": "[T2] 证据乙"},
        DRAMA_CONTEXT,
    )

    assert result.status == "waiting_for_human"
    assert result.requires_human
