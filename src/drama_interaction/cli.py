"""命令行入口：单集 ``run``、HITL ``resume`` 和只读 ``export``。

CLI 只负责边界、持久化和人工交互；生成、校验、渲染及调度均由图节点
实现。每个输入视频文件都对应一个独立的 ``execution_id``，该值同时作为
LangGraph 的 ``configurable.thread_id``。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from langgraph.types import Command, Interrupt

from drama_interaction.config import (
    EVIDENCE_SLICE_CONCURRENCY,
    WORKFLOW_RECURSION_LIMIT,
    Settings,
    SettingsError,
    load_settings,
)
from drama_interaction.context import load_drama_context
from drama_interaction.graph.state import state_to_jsonable


class CLIError(RuntimeError):
    """用户输入、运行状态或持久化失败。"""


_EXECUTION_ID_MAX_LENGTH = 128


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_execution_id() -> str:
    """生成不含路径分隔符的公开执行标识。"""

    return uuid.uuid4().hex


def validate_execution_id(execution_id: str) -> str:
    """校验并返回安全的运行目录标识。"""

    if not isinstance(execution_id, str):
        raise CLIError("execution_id 必须是字符串")
    value = execution_id.strip()
    if (
        not value
        or len(value) > _EXECUTION_ID_MAX_LENGTH
        or value in {".", ".."}
        or any(
            char
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for char in value
        )
    ):
        raise CLIError("execution_id 非法；只能包含 ASCII 字母、数字、下划线和短横线")
    return value


def _resolve_under(root: str | Path, relative_name: str) -> Path:
    """解析运行目录并阻止路径穿越。"""

    root_path = Path(root).expanduser().resolve()
    target = (root_path / relative_name).resolve()
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise CLIError("execution_id 不能跳出运行目录") from exc
    return target


def execution_dir(runs_dir: str | Path, execution_id: str) -> Path:
    """返回一个已校验的执行目录路径（目录本身不自动创建）。"""

    return _resolve_under(runs_dir, validate_execution_id(execution_id))


def state_path(runs_dir: str | Path, execution_id: str) -> Path:
    """返回某次执行的持久化状态文件路径。"""

    return execution_dir(runs_dir, execution_id) / "state.json"


def _atomic_write_json(value: Any, target: str | Path) -> Path:
    """以同目录临时文件 + 替换的方式写 JSON。"""

    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(
                state_to_jsonable(value),
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.write("\n")
            file.flush()
        temporary.replace(destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _read_json(path: str | Path) -> Any:
    source = Path(path)
    if not source.is_file():
        raise CLIError(f"文件不存在: {source}")
    try:
        with source.open(encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        raise CLIError(f"JSON 无法解析: {source}: {exc.msg}") from exc
    except OSError as exc:
        raise CLIError(f"无法读取文件: {source}: {exc}") from exc


def _load_state(runs_dir: str | Path, execution_id: str) -> tuple[Path, dict[str, Any]]:
    validated = validate_execution_id(execution_id)
    path = state_path(runs_dir, validated)
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise CLIError(f"运行状态必须是 JSON 对象: {path}")
    if raw.get("execution_id") != validated:
        raise CLIError("运行状态中的 execution_id 与请求不一致")
    return path, raw


def _settings_for_cli(settings: Settings | None) -> Settings:
    if settings is not None:
        return settings
    try:
        return load_settings()
    except SettingsError as exc:
        raise CLIError(str(exc)) from exc


def _checkpoint_config(execution_id: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": validate_execution_id(execution_id)},
        "max_concurrency": EVIDENCE_SLICE_CONCURRENCY,
        "recursion_limit": WORKFLOW_RECURSION_LIMIT,
    }


def _graph_from_factory(
    settings: Settings,
    graph_factory: Callable[[], Any] | None = None,
) -> Any:
    """惰性创建使用当前配置的工作流图。"""

    if graph_factory is not None:
        return graph_factory()
    try:
        from drama_interaction.graph.builder import build_graph

        return build_graph(settings=settings)
    except Exception as exc:
        # 保留配置或依赖的原始失败原因。
        raise CLIError(f"无法创建工作流图: {exc}") from exc


def _initial_state(
    source: Path,
    execution_id: str,
    run_dir: Path,
    settings: Settings,
) -> dict[str, Any]:
    timestamp = _now()
    try:
        drama_context = load_drama_context(source)
    except (OSError, ValueError) as exc:
        raise CLIError(f"无法加载剧集上下文: {exc}") from exc
    return {
        "execution_id": execution_id,
        "input_path": str(source),
        "run_dir": str(run_dir),
        "evidence_dir": str(settings.evidence_dir),
        "output_dir": str(settings.interaction_v2_dir),
        "drama_context": drama_context,
        "status": "running",
        "created_at": timestamp,
        "updated_at": timestamp,
        "execution": {
            "execution_id": execution_id,
            "input_path": str(source),
            "started_at": timestamp,
            "updated_at": timestamp,
        },
        "metrics": {},
    }


def _interrupt_values(result: Mapping[str, Any]) -> list[Any]:
    raw = result.get("__interrupt__", [])
    if not isinstance(raw, list) or any(
        not isinstance(item, Interrupt) for item in raw
    ):
        raise CLIError("工作流 __interrupt__ 必须是 list[Interrupt]")
    return [state_to_jsonable(item.value) for item in raw]


def _merge_graph_result(
    initial: Mapping[str, Any],
    result: Any,
    *,
    execution_id: str,
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise CLIError("工作流返回值必须是状态对象")
    merged = {**initial, **dict(result)}

    interrupts = _interrupt_values(result)
    if interrupts:
        if merged.get("status") not in {"failed", "completed"}:
            merged["status"] = "waiting_for_human"
    merged["execution_id"] = execution_id
    merged["updated_at"] = _now()
    execution = dict(merged.get("execution") or {})
    execution.update({"execution_id": execution_id, "updated_at": merged["updated_at"]})
    merged["execution"] = execution
    return merged


def _failed_state(state: Mapping[str, Any], error: Exception) -> dict[str, Any]:
    timestamp = _now()
    failed = dict(state)
    failed.update({"status": "failed", "error": str(error), "updated_at": timestamp})
    execution = dict(failed.get("execution") or {})
    execution.update({"status": "failed", "updated_at": timestamp})
    failed["execution"] = execution
    return failed


def _natural_sort_key(path: Path, base_dir: Path) -> list[tuple[int, int | str]]:
    """生成相对于 base_dir 的数字感知自然排序键。"""
    key: list[tuple[int, int | str]] = []
    for part in path.relative_to(base_dir).parts:
        for chunk in re.split(r"(\d+)", part):
            if chunk:
                if chunk.isdecimal():
                    key.append((0, int(chunk)))
                else:
                    key.append((1, chunk.lower()))
    return key


def _iter_episode_files(input_path: str | Path) -> list[Path]:
    source = Path(input_path)
    if not source.exists():
        raise CLIError(f"输入路径不存在: {source}")
    if source.is_file():
        if source.suffix.lower() != ".mp4":
            raise CLIError(f"输入文件必须是 .mp4 视频: {source}")
        return [source]
    files = sorted(
        (
            item
            for item in source.rglob("*")
            if item.is_file() and item.suffix.lower() == ".mp4"
        ),
        key=lambda item: _natural_sort_key(item, source),
    )
    if not files:
        raise CLIError(f"目录中没有 .mp4 视频文件: {source}")
    return files


def run_episode(
    source: str | Path,
    *,
    settings: Settings | None = None,
    graph_factory: Callable[[], Any] | None = None,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """执行一集并持久化最终状态；异常会写成 ``failed`` 状态后抛出。"""

    runtime_settings = _settings_for_cli(settings)
    input_file = Path(source)
    if input_file.suffix.lower() != ".mp4":
        raise CLIError(f"输入文件必须是 .mp4 视频: {input_file}")
    if execution_id is None:
        execution_id = _new_execution_id()
    execution_id = validate_execution_id(execution_id)
    run_directory = execution_dir(runtime_settings.runs_dir, execution_id)
    initial = _initial_state(input_file, execution_id, run_directory, runtime_settings)
    target_state = run_directory / "state.json"
    _atomic_write_json(initial, target_state)

    try:
        workflow = _graph_from_factory(runtime_settings, graph_factory)
        result = workflow.invoke(
            initial,
            _checkpoint_config(execution_id),
            durability="sync",
        )
        final_state = _merge_graph_result(initial, result, execution_id=execution_id)
    except Exception as exc:
        final_state = _failed_state(initial, exc)
        _atomic_write_json(final_state, target_state)
        raise CLIError(f"执行 {execution_id} 失败: {exc}") from exc

    _atomic_write_json(final_state, target_state)
    return final_state


def run_input(
    input_path: str | Path,
    *,
    settings: Settings | None = None,
    graph_factory: Callable[[], Any] | None = None,
    output: TextIO | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """执行单集或目录；目录中某集失败不会阻止后续集。"""

    runtime_settings = _settings_for_cli(settings)
    output_stream = output or sys.stdout
    results: list[dict[str, Any]] = []
    failures = 0
    try:
        episodes = _iter_episode_files(input_path)
    except CLIError as exc:
        print(str(exc), file=sys.stderr)
        return [], 1
    for source in episodes:
        try:
            state = run_episode(
                source,
                settings=runtime_settings,
                graph_factory=graph_factory,
            )
        except CLIError as exc:
            failures += 1
            print(f"{source}: {exc}", file=sys.stderr)
            continue
        results.append(state)
        print(
            f"{state['execution_id']}\t{state.get('status', 'unknown')}\t{source}",
            file=output_stream,
        )
        if state.get("status") == "waiting_for_human":
            print(
                "resume: python -m drama_interaction resume "
                f"--execution-id {state['execution_id']}",
                file=output_stream,
            )
    return results, 1 if failures else 0


def _display_hitl_item(item: Any, index: int, output: TextIO) -> None:
    print(f"\nHITL[{index}]", file=output)
    print(
        json.dumps(state_to_jsonable(item), ensure_ascii=False, indent=2), file=output
    )


def _read_action(
    input_fn: Callable[[str], str],
    output: TextIO,
    index: int,
    actions: Sequence[str],
) -> str:
    """读取当前 HITL 事件允许的操作。"""
    allowed = tuple(actions)
    if not allowed or any(
        action not in {"accept", "edit", "drop"} for action in allowed
    ):
        raise CLIError("HITL 事件缺少合法 actions")
    while True:
        value = (
            input_fn(f"HITL[{index}] action [{'/'.join(allowed)}]: ").strip().lower()
        )
        if value in allowed:
            return value
        print(f"请输入 {'、'.join(allowed)}。", file=output)


def _read_edit(input_fn: Callable[[str], str]) -> Any:
    text = input_fn("输入 edit 的 JSON: ").strip()
    if not text:
        raise CLIError("edit 不能提交空 JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CLIError(f"edit JSON 无法解析: {exc.msg}") from exc


def _human_items(state: Mapping[str, Any]) -> list[Any]:
    queue = state.get("hitl_queue")
    if not isinstance(queue, list):
        return []
    resolved = {
        item.get("event_id")
        for item in state.get("hitl_resolutions", ())
        if isinstance(item, Mapping)
    }
    return [
        item
        for item in queue
        if not isinstance(item, Mapping) or item.get("event_id") not in resolved
    ]


def _apply_human_decision(
    item: Mapping[str, Any], action: str, edited: Any = None
) -> dict[str, Any]:
    decision: dict[str, Any] = {"action": action, "item": dict(item)}
    if action == "edit":
        decision["replacement"] = edited
    return decision


def _resume_payload(decisions: Sequence[Mapping[str, Any]]) -> Any:
    """保持一个稳定、可由 human_gate 节点消费的恢复载荷。"""

    return {"decisions": [state_to_jsonable(decision) for decision in decisions]}


def resume_execution(
    execution_id: str,
    *,
    settings: Settings | None = None,
    graph_factory: Callable[[], Any] | None = None,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> dict[str, Any]:
    """交互处理一个等待人工的执行并从同一 checkpoint 恢复。"""

    runtime_settings = _settings_for_cli(settings)
    validated = validate_execution_id(execution_id)
    target_state, state = _load_state(runtime_settings.runs_dir, validated)
    status = state.get("status")
    if status == "running":
        try:
            workflow = _graph_from_factory(runtime_settings, graph_factory)
            result = workflow.invoke(
                None,
                _checkpoint_config(validated),
                durability="sync",
            )
            resumed = _merge_graph_result(state, result, execution_id=validated)
        except Exception as exc:
            raise CLIError(f"恢复 {validated} 失败: {exc}") from exc
        _atomic_write_json(resumed, target_state)
        return resumed
    if status != "waiting_for_human":
        raise CLIError(
            f"执行 {validated} 当前状态为 {status!r}，只有 running 或 waiting_for_human 可 resume"
        )
    items = _human_items(state)
    if not items:
        raise CLIError(f"执行 {validated} 没有待处理的 HITL 项")
    output_stream = output or sys.stdout
    decisions: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        _display_hitl_item(item, index, output_stream)
        if not isinstance(item, Mapping):
            raise CLIError("HITL 项必须是对象")
        actions = item.get("actions")
        if not isinstance(actions, list) or any(
            not isinstance(action, str) for action in actions
        ):
            raise CLIError("HITL 项缺少 actions 数组")
        action = _read_action(input_fn, output_stream, index, actions)
        edited = _read_edit(input_fn) if action == "edit" else None
        decisions.append(_apply_human_decision(item, action, edited))

    try:
        workflow = _graph_from_factory(runtime_settings, graph_factory)
        result = workflow.invoke(
            Command(resume=_resume_payload(decisions)),
            _checkpoint_config(validated),
            durability="sync",
        )
        resumed = _merge_graph_result(state, result, execution_id=validated)
    except Exception as exc:
        raise CLIError(f"恢复 {validated} 失败: {exc}") from exc
    _atomic_write_json(resumed, target_state)
    return resumed


def _export_items(state: Mapping[str, Any]) -> list[Any]:
    if state.get("status") != "completed":
        raise CLIError(
            f"执行 {state.get('execution_id', '<unknown>')} 尚未完成，不能 export"
        )
    values = state.get("final_interactions")
    if not isinstance(values, list):
        raise CLIError("运行状态缺少 final_interactions 数组")
    return state_to_jsonable(values)


def export_execution(
    execution_id: str,
    *,
    settings: Settings | None = None,
    output_path: str | Path | None = None,
    output: TextIO | None = None,
) -> list[Any]:
    """只从 ``state.json`` 导出已完成的最终互动，不调用工作流。"""

    runtime_settings = _settings_for_cli(settings)
    validated = validate_execution_id(execution_id)
    _, state = _load_state(runtime_settings.runs_dir, validated)
    values = _export_items(state)
    serialized = json.dumps(values, ensure_ascii=False, indent=2) + "\n"
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(serialized, encoding="utf-8", newline="\n")
    else:
        (output or sys.stdout).write(serialized)
    return values


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m drama_interaction")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="执行一集或目录中的所有 .mp4 视频")
    run_parser.add_argument("input", help=".mp4 视频文件或包含视频的目录")

    resume_parser = subparsers.add_parser("resume", help="恢复中断或待人工处理的执行")
    resume_parser.add_argument("--execution-id", required=True)

    export_parser = subparsers.add_parser("export", help="导出已持久化的最终互动")
    export_parser.add_argument("--execution-id", required=True)
    export_parser.add_argument("--output", "-o")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口，返回稳定的进程退出码。"""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            _, code = run_input(args.input)
            return code
        if args.command == "resume":
            state = resume_execution(args.execution_id)
            print(f"{args.execution_id}\t{state.get('status', 'unknown')}")
            return 0
        if args.command == "export":
            export_execution(args.execution_id, output_path=args.output)
            return 0
    except (CLIError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


__all__ = [
    "CLIError",
    "export_execution",
    "execution_dir",
    "main",
    "resume_execution",
    "run_episode",
    "run_input",
    "state_path",
    "validate_execution_id",
]
