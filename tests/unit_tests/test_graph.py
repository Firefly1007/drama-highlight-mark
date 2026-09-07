"""V2 LangGraph 主链最小回归测试。"""

import base64
import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pytest import MonkeyPatch

from drama_interaction.config import EVIDENCE_SLICE_CONCURRENCY, Settings
from drama_interaction.context import DramaContext
from drama_interaction.graph import nodes as graph_nodes
from drama_interaction.graph.builder import (
    _checkpoint_serde,
    build_graph,
    build_slice_graph,
)
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
        evidence_dir=tmp_path / "data" / "evidence",
        interaction_v2_dir=tmp_path / "data" / "interaction_v2",
        runs_dir=tmp_path / "data" / "interaction_v2" / "runs",
    )


def _write_dummy_video(tmp_path: Path) -> Path:
    """创建用于图层测试的伪 .mp4 文件。"""
    path = tmp_path / "测试剧" / "第1集.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"dummy mp4 content")
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
        specialist_barrier: threading.Barrier | None = None,
    ) -> None:
        self.responses = responses
        self.fail_labels = fail_labels or set()
        self.specialist_barrier = specialist_barrier
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
        if self.gateway.specialist_barrier is not None:
            self.gateway.specialist_barrier.wait(timeout=3)
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


def _patch_extraction(
    monkeypatch: MonkeyPatch,
    *,
    duration_ms: int = 5000,
    empty_starts: set[int] | None = None,
    observer_barrier: threading.Barrier | None = None,
    preparation_barrier: threading.Barrier | None = None,
    slice_barrier: threading.Barrier | None = None,
) -> list[tuple[str, int]]:
    """替换媒体和 provider 调用，保留真实的图编排。"""
    calls: list[tuple[str, int]] = []
    empty = empty_starts or set()
    synchronized_starts: set[int] = set()
    synchronized_starts_lock = threading.Lock()

    def marker_from_data_url(data_url: str) -> int:
        return int(base64.b64decode(data_url.rsplit(",", 1)[1]).decode().split(":")[1])

    def record_observer(name: str, start_ms: int) -> None:
        if observer_barrier is not None:
            observer_barrier.wait(timeout=3)
        calls.append((name, start_ms))

    def fake_extract_mix(_video_path: Path, output_path: Path) -> Path:
        if preparation_barrier is not None:
            preparation_barrier.wait(timeout=3)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"mix")
        calls.append(("extract_mix", -1))
        return output_path

    def fake_separate(video_path: Path, _mix_path: str, settings: Settings):
        video = Path(video_path)
        audio_dir = settings.evidence_dir / video.parent.name / f"{video.stem}.audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        background = audio_dir / "background.mp3"
        dialogue = audio_dir / "dialogue.mp3"
        background.write_bytes(b"background")
        dialogue.write_bytes(b"dialogue")
        calls.append(("separate_audio", -1))
        return background, dialogue

    def fake_transcribe(
        _video_path: Path,
        _settings: Settings,
        episode_duration_ms: int,
        *,
        characters: tuple[str, ...] = (),
    ):
        calls.append(("transcribe_audio", -1))
        return [
            TranscriptSegment(
                id="T1", start_ms=0, end_ms=episode_duration_ms, text="你必须做出选择。"
            )
        ]

    def fake_cut(_input_path: str, output_path: Path, _duration_ms: int) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"background")
        return output_path

    def fake_frames(_video_path: Path, timestamps_ms: list[int], output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        start_ms = timestamps_ms[0] // 3000 * 3000
        if slice_barrier is not None:
            with synchronized_starts_lock:
                wait_for_batch = (
                    start_ms not in synchronized_starts
                    and len(synchronized_starts) < slice_barrier.parties
                )
                if wait_for_batch:
                    synchronized_starts.add(start_ms)
            if wait_for_batch:
                slice_barrier.wait(timeout=3)
        frame = output_dir / "frame_000.jpg"
        frame.write_bytes(f"slice:{start_ms}".encode())
        calls.append(("prepare_frames", start_ms))
        return [frame]

    def fake_slice_audio(
        _input_path: str, start_ms: int, _end_ms: int, output_path: Path
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"slice:{start_ms}".encode())
        calls.append(("prepare_slice_audio", start_ms))
        return output_path

    def fake_ocr(
        data_urls: list[str], _settings: Settings, _client: object
    ) -> list[str]:
        start_ms = marker_from_data_url(data_urls[0])
        record_observer("ocr", start_ms)
        return [] if start_ms in empty else [f"文字 {start_ms}"]

    def fake_vlm(
        data_urls: list[str], _settings: Settings, _client: object
    ) -> tuple[list[str], list[str]]:
        start_ms = marker_from_data_url(data_urls[0])
        record_observer("vlm", start_ms)
        return ([], []) if start_ms in empty else ([f"画面 {start_ms}"], [])

    def fake_audio(audio_path: Path, _settings: Settings, _client: object):
        start_ms = int(audio_path.read_text().split(":")[1])
        record_observer("audio", start_ms)
        return ([], []) if start_ms in empty else ([f"声音 {start_ms}"], [])

    def fake_probe(_path: Path) -> int:
        if preparation_barrier is not None:
            preparation_barrier.wait(timeout=3)
        return duration_ms

    monkeypatch.setattr(graph_nodes, "probe_video_duration_ms", fake_probe)
    monkeypatch.setattr(graph_nodes, "extract_audio_flac", fake_extract_mix)
    monkeypatch.setattr(graph_nodes, "separate_episode_audio", fake_separate)
    monkeypatch.setattr(graph_nodes, "transcribe_episode_dialogue", fake_transcribe)
    monkeypatch.setattr(graph_nodes, "cut_audio_hard", fake_cut)
    monkeypatch.setattr(graph_nodes, "extract_frames", fake_frames)
    monkeypatch.setattr(graph_nodes, "slice_audio", fake_slice_audio)
    monkeypatch.setattr(graph_nodes, "OpenAI", lambda **_kwargs: MagicMock())
    monkeypatch.setattr(graph_nodes, "run_qwen_ocr", fake_ocr)
    monkeypatch.setattr(graph_nodes, "run_qwen_vlm", fake_vlm)
    monkeypatch.setattr(graph_nodes, "run_qwen_audio_observer", fake_audio)
    return calls


def _graph(
    settings: Settings,
    gateway: FakeGateway,
    monkeypatch: MonkeyPatch,
    *,
    patch_extraction: bool = True,
):
    """构造使用显式内存 checkpoint 的测试图。"""
    monkeypatch.setattr(
        graph_nodes,
        "_specialist",
        lambda specialist_type, _gateway, *, drama_context, evidence_service, existing_derived: (
            FakeSpecialist(
                specialist_type,
                gateway,
                evidence_service=evidence_service,
                existing_derived=existing_derived,
            )
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
    if patch_extraction:
        _patch_extraction(monkeypatch)
    return build_graph(
        settings=settings,
        checkpointer=InMemorySaver(serde=_checkpoint_serde()),
        gateway=gateway,
    )


def _invoke_config(execution_id: str) -> dict[str, Any]:
    """构造 LangGraph thread 配置。"""
    return {
        "configurable": {"thread_id": execution_id},
        "max_concurrency": EVIDENCE_SLICE_CONCURRENCY,
    }


def _interrupt_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    """提取 HITL interrupt 中的事件列表。"""
    interrupts = result["__interrupt__"]
    return interrupts[0].value["events"]


def test_graph_registers_five_direct_specialist_nodes(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """父图直接注册五个 Specialist 节点，不再套单节点子图。"""
    graph = _graph(
        _settings(tmp_path), FakeGateway({}), monkeypatch, patch_extraction=False
    )

    specialist_types = (
        "emotion_button",
        "repeat_keyline",
        "instant_vote",
        "deferred_vote",
        "side_comment",
    )
    xray_nodes = graph.get_graph(xray=1).nodes
    assert all(
        f"specialist_{specialist_type}" in xray_nodes
        for specialist_type in specialist_types
    )
    assert not any(node.endswith(":run") for node in xray_nodes)


def test_graph_completes_with_string_interaction_type(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """主链应完成并输出字符串 type。"""
    input_path = _write_dummy_video(tmp_path)
    gateway = FakeGateway(
        {
            "specialist:instant_vote": {
                "specialist_type": "instant_vote",
                "candidates": [_instant_candidate()],
                "abstentions": [],
            }
        }
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


def test_graph_runs_specialists_in_parallel(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """五个独立 Specialist 必须在同一图步骤并行执行。"""
    gateway = FakeGateway(
        {}, specialist_barrier=threading.Barrier(len(graph_nodes.SPECIALIST_TYPES))
    )
    input_path = _write_dummy_video(tmp_path)
    result = _graph(_settings(tmp_path), gateway, monkeypatch).invoke(
        _initial_state(tmp_path, input_path, "run-specialist-parallel"),
        config={
            **_invoke_config("run-specialist-parallel"),
            "max_concurrency": len(graph_nodes.SPECIALIST_TYPES),
        },
    )

    assert result["status"] == "completed"


def test_graph_semantic_scheduler_keeps_only_returned_candidate_id(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """真实重叠候选应调用语义调度并只保留合法返回 ID。"""
    input_path = _write_dummy_video(tmp_path)
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
    assert result["scheduler_decision"]["selected_candidate_ids"] == ["candidate-0002"]
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
    late = Candidate.model_validate({"candidate_id": "late", **_instant_candidate()})
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
    input_path = _write_dummy_video(tmp_path)
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


def test_graph_structure_has_isolated_extraction_nodes_and_no_adapter(
    tmp_path: Path,
) -> None:
    """生产图把媒体、三路观察、合并和持久化拆成独立节点。"""
    settings = _settings(tmp_path)
    workflow = build_graph(
        settings=settings,
        checkpointer=InMemorySaver(serde=_checkpoint_serde()),
        gateway=FakeGateway({}),
    )
    assert {
        "extract_mix",
        "separate_audio",
        "transcribe_audio",
        "prepare_background",
        "dispatch_slice_batch",
        "slice",
        "merge_slice_batch",
        "assemble_evidence",
        "persist_evidence",
    } <= set(workflow.nodes)
    assert {
        "slice:prepare_frames",
        "slice:prepare_slice_audio",
        "slice:observe_ocr",
        "slice:observe_vlm",
        "slice:observe_audio",
        "slice:merge_slice_result",
    } <= set(workflow.get_graph(xray=1).nodes)
    edges = {(edge.source, edge.target) for edge in workflow.get_graph().edges}
    assert {
        ("separate_audio", "transcribe_audio"),
        ("separate_audio", "prepare_background"),
    } <= edges
    assert ("transcribe_audio", "prepare_background") not in edges
    assert "adapter" not in workflow.nodes
    assert "observe_slice" not in workflow.nodes


def test_media_and_provider_nodes_have_single_responsibility(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """时长探测、混音抽取、分离和 ASR 可分别替换与测试。"""
    input_path = _write_dummy_video(tmp_path)
    settings = _settings(tmp_path)
    calls = _patch_extraction(monkeypatch, duration_ms=4321)

    state = _initial_state(tmp_path, input_path, "run-duration")
    prepared = graph_nodes.media_prepare_node(state)
    assert prepared["episode_duration_ms"] == 4321
    assert prepared["metrics"] == {"episode_duration_ms": 4321}

    mixed = graph_nodes.extract_mix_node({**state, **prepared})
    separated = graph_nodes.separate_audio_node(
        {**state, **prepared, **mixed}, settings=settings
    )
    transcribed = graph_nodes.transcribe_audio_node(
        {**state, **prepared, **mixed, **separated}, settings=settings
    )

    assert calls[:3] == [
        ("extract_mix", -1),
        ("separate_audio", -1),
        ("transcribe_audio", -1),
    ]
    assert Path(mixed["mix_audio_path"]).is_file()
    assert Path(separated["background_audio_path"]).is_file()
    assert Path(separated["dialogue_audio_path"]).is_file()
    assert transcribed["transcript_segments"][0].end_ms == 4321


def test_graph_starts_media_probe_and_mix_extraction_in_parallel(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """ffprobe 与 ffmpeg 音频抽取不互相等待，完成后才进入分离。"""
    _patch_extraction(
        monkeypatch,
        preparation_barrier=threading.Barrier(2),
    )
    input_path = _write_dummy_video(tmp_path)
    result = _graph(
        _settings(tmp_path), FakeGateway({}), monkeypatch, patch_extraction=False
    ).invoke(
        _initial_state(tmp_path, input_path, "run-preparation-parallel"),
        config=_invoke_config("run-preparation-parallel"),
    )

    assert result["status"] == "completed"


def test_slice_subgraph_observers_run_in_parallel(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """单个切片子图内的三路观察应并行执行。"""
    barrier = threading.Barrier(3)
    calls = _patch_extraction(monkeypatch, observer_barrier=barrier)
    input_path = _write_dummy_video(tmp_path)
    result = build_slice_graph(settings=_settings(tmp_path)).invoke(
        {
            "input_path": str(input_path),
            "run_dir": str(tmp_path / "runs" / "run-slice"),
            "background_wav_path": str(tmp_path / "background.wav"),
            "slice_index": 0,
            "slice_start_ms": 0,
            "slice_end_ms": 3000,
        }
    )

    assert result["slice_results"]["0"]["start_ms"] == 0
    assert {
        name
        for name, start_ms in calls
        if start_ms == 0 and name in {"ocr", "vlm", "audio"}
    } == {
        "ocr",
        "vlm",
        "audio",
    }


def test_graph_resumes_after_merged_slice_batch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """整批合并 checkpoint 后恢复时不重复观察已完成切片。"""
    calls = _patch_extraction(monkeypatch)
    graph = _graph(
        _settings(tmp_path), FakeGateway({}), monkeypatch, patch_extraction=False
    )
    input_path = _write_dummy_video(tmp_path)
    config = _invoke_config("run-resume")

    graph.invoke(
        _initial_state(tmp_path, input_path, "run-resume"),
        config=config,
        interrupt_after=["merge_slice_batch"],
    )
    checkpoint = graph.get_state(config).values
    assert checkpoint["next_slice_index"] == 2

    result = graph.invoke(None, config=config)

    assert result["status"] == "completed"
    assert [item.start_ms for item in result["evidence"].observations] == [0, 3000]
    observer_calls = [
        (name, start_ms) for name, start_ms in calls if name in {"ocr", "vlm", "audio"}
    ]
    assert len(observer_calls) == 6


def test_graph_runs_four_slice_subgraphs_in_parallel_and_merges_in_order(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """父图每批并行四片，Observation 仍按时间顺序写入。"""
    calls = _patch_extraction(
        monkeypatch,
        duration_ms=12_001,
        slice_barrier=threading.Barrier(EVIDENCE_SLICE_CONCURRENCY),
    )
    input_path = _write_dummy_video(tmp_path)
    result = _graph(
        _settings(tmp_path), FakeGateway({}), monkeypatch, patch_extraction=False
    ).invoke(
        _initial_state(tmp_path, input_path, "run-four-slices"),
        config=_invoke_config("run-four-slices"),
    )

    assert sorted(start_ms for name, start_ms in calls if name == "prepare_frames") == [
        0,
        3000,
        6000,
        9000,
        12000,
    ]
    assert [item.start_ms for item in result["evidence"].observations] == [
        0,
        3000,
        6000,
        9000,
        12000,
    ]


def test_empty_slice_is_checkpointed_without_observation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """三路均空的切片也会在整批合并后推进索引。"""
    calls = _patch_extraction(monkeypatch, empty_starts={0})
    graph = _graph(
        _settings(tmp_path), FakeGateway({}), monkeypatch, patch_extraction=False
    )
    input_path = _write_dummy_video(tmp_path)
    config = _invoke_config("run-empty-resume")

    graph.invoke(
        _initial_state(tmp_path, input_path, "run-empty-resume"),
        config=config,
        interrupt_after=["merge_slice_batch"],
    )
    assert graph.get_state(config).values["next_slice_index"] == 2

    result = graph.invoke(None, config=config)

    assert [item.start_ms for item in result["evidence"].observations] == [3000]
    assert [
        (name, start_ms) for name, start_ms in calls if name in {"ocr", "vlm", "audio"}
    ].count(("ocr", 0)) == 1
