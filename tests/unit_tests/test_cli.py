"""CLI 人工恢复边界测试。"""

import io
import json
from pathlib import Path

import pytest
from langgraph.types import Interrupt

from drama_interaction.cli import (
    CLIError,
    _checkpoint_config,
    _human_items,
    _interrupt_values,
    _iter_episode_files,
    _load_state,
    _merge_graph_result,
    _read_action,
    resume_execution,
    run_episode,
    run_input,
)
from drama_interaction.config import EVIDENCE_SLICE_CONCURRENCY, Settings
from drama_interaction.graph.state import SPECIALIST_TYPES


def _settings(tmp_path: Path) -> Settings:
    """构造只使用临时目录的测试配置。"""

    return Settings(
        llm_model_id="test-model",
        llm_api_key="test-key",
        llm_base_url="https://llm.example/v1",
        checkpoint_database_url="postgresql://user:pass@localhost/test",
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
        evidence_dir=tmp_path / "evidence",
        interaction_v2_dir=tmp_path / "interaction_v2",
        runs_dir=tmp_path / "runs",
    )


def test_checkpoint_config_allows_all_specialists() -> None:
    assert _checkpoint_config("run-concurrency")["max_concurrency"] == (
        max(EVIDENCE_SLICE_CONCURRENCY, len(SPECIALIST_TYPES))
    )


def test_read_action_only_shows_allowed_actions():
    """非法操作重试时只展示事件声明的 actions。"""

    prompts: list[str] = []
    values = iter(("accept", "drop"))
    output = io.StringIO()

    result = _read_action(
        lambda prompt: prompts.append(prompt) or next(values),
        output,
        1,
        ["drop"],
    )

    assert result == "drop"
    assert prompts == [
        "HITL[1] action [drop]: ",
        "HITL[1] action [drop]: ",
    ]
    assert output.getvalue() == "请输入 drop。\n"


def test_interrupt_values_accepts_langgraph_interrupt_list():
    result = {"__interrupt__": [Interrupt(value={"event": "review"})]}

    assert _interrupt_values(result) == [{"event": "review"}]


@pytest.mark.parametrize("raw", [(), "review", object()])
def test_interrupt_values_rejects_non_tuple_shapes(raw):
    with pytest.raises(CLIError, match="list\\[Interrupt\\]"):
        _interrupt_values({"__interrupt__": raw})


def test_interrupt_values_rejects_non_interrupt_list_items():
    with pytest.raises(CLIError, match="list\\[Interrupt\\]"):
        _interrupt_values({"__interrupt__": ["review"]})


def test_merge_graph_result_rejects_missing_graph_state():
    with pytest.raises(CLIError, match="工作流返回值"):
        _merge_graph_result({}, None, execution_id="test-execution")


def test_human_items_does_not_fall_back_to_interrupts():
    assert (
        _human_items({"hitl_queue": [], "interrupts": [{"event_id": "old-event"}]})
        == []
    )


@pytest.mark.parametrize("state", [{}, {"execution_id": "other-execution"}])
def test_load_state_requires_requested_execution_id(tmp_path: Path, state):
    settings = _settings(tmp_path)
    execution_id = "test-execution"
    state_file = settings.runs_dir / execution_id / "state.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(CLIError, match="execution_id"):
        _load_state(settings.runs_dir, execution_id)


def test_resume_failure_keeps_waiting_state(tmp_path: Path):
    """恢复图调用失败时不提前覆盖等待中的状态。"""

    settings = _settings(tmp_path)
    execution_id = "test-execution"
    state = {
        "execution_id": execution_id,
        "status": "waiting_for_human",
        "hitl_queue": [
            {
                "event_id": "candidate-review:1",
                "kind": "candidate_review",
                "actions": ["drop"],
            }
        ],
        "hitl_resolutions": [],
    }
    state_file = settings.runs_dir / execution_id / "state.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(json.dumps(state), encoding="utf-8")

    class FailingGraph:
        def invoke(self, *_args, **_kwargs):
            raise RuntimeError("checkpoint unavailable")

    with pytest.raises(CLIError, match="恢复 .* 失败"):
        resume_execution(
            execution_id,
            settings=settings,
            graph_factory=lambda: FailingGraph(),
            input_fn=lambda _prompt: "drop",
            output=io.StringIO(),
        )

    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["status"] == "waiting_for_human"
    assert persisted["hitl_queue"] == state["hitl_queue"]


def test_iter_episode_files_single_file_mp4(tmp_path: Path):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"dummy")
    assert _iter_episode_files(video) == [video]


def test_iter_episode_files_single_file_non_mp4_raises(tmp_path: Path):
    not_video = tmp_path / "test.json"
    not_video.write_text("{}", encoding="utf-8")
    with pytest.raises(CLIError, match="必须是 .mp4 视频"):
        _iter_episode_files(not_video)


def test_iter_episode_files_natural_sorting_and_recursive(tmp_path: Path):
    drama_dir = tmp_path / "drama"
    sub_dir = drama_dir / "season1"
    sub_dir.mkdir(parents=True)

    ep10 = sub_dir / "第10集.mp4"
    ep2 = sub_dir / "第2集.mp4"
    ep1 = sub_dir / "第1集.mp4"
    ep20 = sub_dir / "第20集.mp4"
    txt = sub_dir / "notes.txt"
    for file in (ep10, ep2, ep1, ep20, txt):
        file.write_bytes(b"")

    episodes = _iter_episode_files(drama_dir)
    assert episodes == [ep1, ep2, ep10, ep20]


def test_iter_episode_files_mixed_digit_and_alpha_no_type_error(tmp_path: Path):
    """测试包含纯数字和纯字母开头的视频文件自然排序时不会触发 TypeError。"""
    drama_dir = tmp_path / "mixed"
    drama_dir.mkdir()
    f1 = drama_dir / "1.mp4"
    f2 = drama_dir / "2.mp4"
    f10 = drama_dir / "10.mp4"
    f_bonus = drama_dir / "bonus.mp4"
    for file in (f10, f_bonus, f1, f2):
        file.write_bytes(b"")

    episodes = _iter_episode_files(drama_dir)
    assert episodes == [f1, f2, f10, f_bonus]


def test_iter_episode_files_empty_dir_raises(tmp_path: Path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(CLIError, match="没有 .mp4 视频文件"):
        _iter_episode_files(empty_dir)


def test_run_episode_rejects_non_mp4(tmp_path: Path):
    bad = tmp_path / "ep.json"
    bad.write_text("{}", encoding="utf-8")
    settings = _settings(tmp_path)
    with pytest.raises(CLIError, match="必须是 .mp4 视频"):
        run_episode(bad, settings=settings)


def test_run_input_continues_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    drama_dir = tmp_path / "drama"
    drama_dir.mkdir()
    ep1 = drama_dir / "ep1.mp4"
    ep2 = drama_dir / "ep2.mp4"
    ep1.write_bytes(b"")
    ep2.write_bytes(b"")

    settings = _settings(tmp_path)

    call_count = 0

    def fake_run_episode(source, **kwargs):
        nonlocal call_count
        call_count += 1
        if "ep1" in str(source):
            raise CLIError("ep1 failed")
        return {"execution_id": "run-ep2", "status": "completed"}

    monkeypatch.setattr("drama_interaction.cli.run_episode", fake_run_episode)

    output = io.StringIO()
    results, exit_code = run_input(drama_dir, settings=settings, output=output)

    assert call_count == 2
    assert len(results) == 1
    assert results[0]["execution_id"] == "run-ep2"
    assert exit_code == 1


@pytest.mark.parametrize("kind", ["missing", "empty-dir"])
def test_run_input_reports_discovery_failure_as_exit_code_one(
    tmp_path: Path,
    kind: str,
    capsys: pytest.CaptureFixture[str],
):
    """测试发现阶段的失败只打印并返回 ([], 1)，不向调用方抛异常。"""
    settings = _settings(tmp_path)
    if kind == "missing":
        target = tmp_path / "不存在"
        expected = "输入路径不存在"
    else:
        target = tmp_path / "drama"
        target.mkdir()
        (target / "notes.txt").write_text("x", encoding="utf-8")
        expected = "目录中没有 .mp4 视频文件"

    results, exit_code = run_input(target, settings=settings, output=io.StringIO())

    assert results == []
    assert exit_code == 1
    assert expected in capsys.readouterr().err
