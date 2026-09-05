"""CLI 人工恢复边界测试。"""

import io
import json
from pathlib import Path

import pytest
from langgraph.types import Interrupt

from drama_interaction.cli import (
    CLIError,
    _human_items,
    _interrupt_values,
    _load_state,
    _merge_graph_result,
    _read_action,
    resume_execution,
)
from drama_interaction.config import Settings


def _settings(tmp_path: Path) -> Settings:
    """构造只使用临时目录的测试配置。"""

    return Settings(
        llm_model_id="test-model",
        llm_api_key="test-key",
        llm_base_url="https://llm.example/v1",
        checkpoint_database_url="postgresql://user:pass@localhost/test",
        evidence_dir=tmp_path / "evidence",
        interaction_v2_dir=tmp_path / "interaction_v2",
        runs_dir=tmp_path / "runs",
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
    assert _human_items(
        {"hitl_queue": [], "interrupts": [{"event_id": "old-event"}]}
    ) == []


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
