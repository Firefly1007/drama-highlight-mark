"""V2 LangGraph 主链最小回归测试。"""

import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pytest import MonkeyPatch

from drama_interaction.config import Settings
from drama_interaction.context import DramaContext
from drama_interaction.graph import nodes as graph_nodes
from drama_interaction.graph.builder import _checkpoint_serde, build_graph
from drama_interaction.graph.nodes import render_node
from drama_interaction.llm import LLMNetworkExhaustedError
from drama_interaction.scheduling.semantic import SemanticSelection
from drama_interaction.schemas.candidate import Candidate, SpecialistResult
from drama_interaction.schemas.evidence import EvidenceDocument, TranscriptSegment


def _settings(tmp_path: Path) -> Settings:
    """构造不读取外部配置的测试设置。"""
    return Settings(
        llm_model_id="test-model",
        llm_api_key="test-key",
        llm_base_url="https://example.test/v1",
        checkpoint_database_url="postgresql://test:test@localhost/test",
        evidence_dir=tmp_path / "data" / "evidence",
        interaction_v2_dir=tmp_path / "data" / "interaction_v2",
        runs_dir=tmp_path / "data" / "interaction_v2" / "runs",
    )


def _write_segments(tmp_path: Path) -> Path:
    """写入一条用于图测试的 V1 片段。"""
    path = tmp_path / "segments.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "start": "00:00:00.000",
                    "end": "00:00:05.000",
                    "text": "你必须做出选择。",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _initial_state(
    tmp_path: Path,
    input_path: Path,
    execution_id: str,
) -> dict[str, str]:
    """构造图入口状态。"""
    return {
        "execution_id": execution_id,
        "input_path": str(input_path),
        "run_dir": str(tmp_path / "runs" / execution_id),
        "evidence_dir": str(tmp_path / "evidence"),
        "output_dir": str(tmp_path / "output"),
        "drama_context": DramaContext(name="测试剧"),
    }


def _abstention(specialist_type: str) -> dict[str, Any]:
    """返回一份明确弃权的 Specialist 响应。"""
    return {
        "specialist_type": specialist_type,
        "candidates": [],
        "abstentions": [
            {"specialist_type": specialist_type, "reason": "测试中无额外互动候选"}
        ],
    }


def _instant_candidate() -> dict[str, Any]:
    """返回一条合法的即时投票候选。"""
    return {
        "specialist_type": "instant_vote",
        "evidence_ids": ["T1"],
        "trigger_anchor": {"transcript_segment_id": "T1"},
        "payload": {"question": "你站谁？", "options": ["甲", "乙"]},
    }


def _emotion_candidate() -> dict[str, Any]:
    """返回一条合法的情绪按钮候选。"""
    return {
        "specialist_type": "emotion_button",
        "evidence_ids": ["T1"],
        "trigger_anchor": {"transcript_segment_id": "T1"},
        "payload": {"button_id": "cool", "text": "太解气了"},
    }


def _side_comment_candidate() -> dict[str, Any]:
    """返回一条合法的边看边聊候选。"""
    return {
        "specialist_type": "side_comment",
        "evidence_ids": ["T1"],
        "trigger_anchor": {"transcript_segment_id": "T1"},
        "payload": {"text": "这也太敢说了吧！", "mood": "shock"},
    }


class FakeGateway:
    """保存测试分支响应，不实现已移除的文本 JSON 接口。"""

    def __init__(
        self,
        responses: dict[str, Any],
        *,
        fail_labels: set[str] | None = None,
    ) -> None:
        self.responses = responses
        self.fail_labels = fail_labels or set()
        self.specialist_calls: list[tuple[str, str, object]] = []


class FakeSpecialist:
    """只用于图层测试的分支 Specialist。"""

    def __init__(
        self,
        specialist_type: str,
        gateway: FakeGateway,
        *,
        evidence_service: object,
        existing_derived: object,
    ) -> None:
        self.specialist_type = specialist_type
        self.gateway = gateway
        self.evidence_service = evidence_service
        self.existing_derived = existing_derived

    def run(self, timeline: str) -> Any:
        """按分支返回结构化测试结果。"""
        self.gateway.specialist_calls.append(
            (self.specialist_type, timeline, self.evidence_service)
        )
        label = f"specialist:{self.specialist_type}"
        if label in self.gateway.fail_labels:
            raise LLMNetworkExhaustedError(
                call_label=label,
                model="test-model",
                attempts=2,
                original_error=ConnectionError("test network down"),
            )
        return SpecialistResult.model_validate(
            self.gateway.responses.get(label, _abstention(self.specialist_type))
        )


def _graph(
    settings: Settings,
    gateway: FakeGateway,
    monkeypatch: MonkeyPatch,
):
    """构造使用显式内存 checkpoint 的测试图。"""
    monkeypatch.setattr(
        graph_nodes,
        "_specialist",
        lambda specialist_type, _gateway, *, drama_context, evidence_service, existing_derived: FakeSpecialist(
            specialist_type,
            gateway,
            evidence_service=evidence_service,
            existing_derived=existing_derived,
        ),
    )

    def fake_semantic_selection(
        _gateway: FakeGateway,
        _candidates_by_id: object,
        _conflict_groups: object,
        _evidence_timelines: object,
        _drama_context: DramaContext,
        _settings: Settings,
    ) -> SemanticSelection:
        """为图层测试提供已结构化的语义调度结果。"""
        response = gateway.responses["scheduling.semantic"]
        return SemanticSelection(
            status="selected",
            selected_candidate_ids=response["selected_candidate_ids"],
            reason=response.get("reason"),
        )

    monkeypatch.setattr(
        "drama_interaction.scheduling.semantic.select_candidate_ids",
        fake_semantic_selection,
    )
    return build_graph(
        settings=settings,
        checkpointer=InMemorySaver(serde=_checkpoint_serde()),
        gateway=gateway,
    )


def _invoke_config(execution_id: str) -> dict[str, dict[str, str]]:
    """构造 LangGraph thread 配置。"""
    return {"configurable": {"thread_id": execution_id}}


def _interrupt_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    """提取 HITL interrupt 中的事件列表。"""
    interrupts = result["__interrupt__"]
    return interrupts[0].value["events"]


def test_graph_embeds_five_compiled_specialist_subgraphs(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """父图节点应是已编译子图，xray 能展开各自的 run 节点。"""
    graph = _graph(_settings(tmp_path), FakeGateway({}), monkeypatch)

    assert all(
        isinstance(
            graph.nodes[f"specialist_{specialist_type}"].bound,
            CompiledStateGraph,
        )
        for specialist_type in (
            "emotion_button",
            "repeat_keyline",
            "instant_vote",
            "deferred_vote",
            "side_comment",
        )
    )
    xray_nodes = graph.get_graph(xray=1).nodes
    assert all(
        f"specialist_{specialist_type}:run" in xray_nodes
        for specialist_type in (
            "emotion_button",
            "repeat_keyline",
            "instant_vote",
            "deferred_vote",
            "side_comment",
        )
    )


def test_graph_completes_with_string_interaction_type(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """主链应完成并输出字符串 type。"""
    input_path = _write_segments(tmp_path)
    gateway = FakeGateway(
        {"specialist:instant_vote": {
            "specialist_type": "instant_vote",
            "candidates": [_instant_candidate()],
            "abstentions": [],
        }}
    )
    settings = _settings(tmp_path)
    result = _graph(settings, gateway, monkeypatch).invoke(
        _initial_state(tmp_path, input_path, "run-normal"),
        config=_invoke_config("run-normal"),
    )

    assert result["status"] == "completed"
    output = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
    assert output == [
        {
            "id": 1,
            "type": "instant_vote",
            "show_at": 0,
            "duration_ms": 3500,
            "payload": {"question": "你站谁？", "options": ["甲", "乙"]},
        }
    ]
    assert {call[0] for call in gateway.specialist_calls} == {
        "emotion_button",
        "repeat_keyline",
        "instant_vote",
        "deferred_vote",
        "side_comment",
    }
    assert len({id(call[2]) for call in gateway.specialist_calls}) == 5


def test_graph_semantic_scheduler_keeps_only_returned_candidate_id(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """真实重叠候选应调用语义调度并只保留合法返回 ID。"""
    input_path = _write_segments(tmp_path)
    gateway = FakeGateway(
        {
            "specialist:emotion_button": {
                "specialist_type": "emotion_button",
                "candidates": [_emotion_candidate()],
                "abstentions": [],
            },
            "specialist:side_comment": {
                "specialist_type": "side_comment",
                "candidates": [_side_comment_candidate()],
                "abstentions": [],
            },
            "scheduling.semantic": {
                "selected_candidate_ids": ["candidate-0002"],
                "reason": "保留边看边聊互动",
            },
        }
    )
    settings = _settings(tmp_path)
    result = _graph(settings, gateway, monkeypatch).invoke(
        _initial_state(tmp_path, input_path, "run-semantic"),
        config=_invoke_config("run-semantic"),
    )

    assert result["status"] == "completed"
    assert gateway.responses["scheduling.semantic"]["selected_candidate_ids"] == [
        "candidate-0002"
    ]
    assert result["scheduler_decision"]["selected_candidate_ids"] == [
        "candidate-0002"
    ]
    output = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
    assert len(output) == 1
    assert output[0]["type"] == "side_comment"


def test_render_node_numbers_candidates_after_sorting() -> None:
    """渲染排序后应从 1 开始统一编号。"""
    document = EvidenceDocument(
        episode_duration_ms=10_000,
        transcript_segments=[
            TranscriptSegment(id="T2", start_ms=0, end_ms=1000, text="较早"),
            TranscriptSegment(id="T1", start_ms=2000, end_ms=3000, text="较晚"),
        ],
    )
    late = Candidate.model_validate(
        {"candidate_id": "late", **_instant_candidate()}
    )
    early = Candidate.model_validate(
        {
            "candidate_id": "early",
            **_instant_candidate(),
            "evidence_ids": ["T2"],
            "trigger_anchor": {"transcript_segment_id": "T2"},
        }
    )

    result = render_node(
        {
            "evidence": document,
            "candidate_pool": [late, early],
            "execution_id": "run-render",
        },
        settings=None,
    )

    assert result["rendered_candidates"]["early"].id == 1
    assert result["rendered_candidates"]["late"].id == 2


def test_graph_network_exhaustion_interrupts_then_drop_completes(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Specialist 网络重试耗尽应暂停，终端 drop 后完成。"""
    input_path = _write_segments(tmp_path)
    gateway = FakeGateway(
        {},
        fail_labels={"specialist:instant_vote"},
    )
    settings = _settings(tmp_path)
    graph = _graph(settings, gateway, monkeypatch)
    config = _invoke_config("run-network")
    first = graph.invoke(
        _initial_state(tmp_path, input_path, "run-network"),
        config=config,
    )

    events = _interrupt_events(first)
    assert len(events) == 1
    assert events[0]["event_type"] == "network_exhausted"

    resumed = graph.invoke(
        Command(
            resume={
                "decisions": [{"item": events[0], "action": "drop"}],
            }
        ),
        config=config,
    )

    assert resumed["status"] == "completed"
    assert resumed["final_interactions"] == []
