"""把当前 Specialist 可见证据渲染为可复制的时间线文本。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from drama_interaction.media import calculate_slices
from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    Observation,
    TranscriptSegment,
    validate_derived_observations,
)
from drama_interaction.schemas.interaction import InteractionType


def _span(entry: Any) -> tuple[int, int]:
    return entry.start_ms, entry.end_ms


def _content_lines(entry: Observation | DerivedObservation) -> list[str]:
    """按稳定字段顺序整理观察文本。"""
    lines: list[str] = []
    for label, values in (
        ("画面", entry.visual_observations),
        ("屏幕文字", entry.onscreen_texts),
        ("音频", entry.audio_observations),
        ("不确定性", entry.uncertainty),
    ):
        for value in values:
            lines.append(f"{label}：{value}")
    return lines or ["观察：无文字描述"]


def _entry_line(entry: Any, *, include_time: bool = True) -> str:
    """渲染一条台词或观察。"""
    start, end = _span(entry)
    time_str = f" start_ms={start} end_ms={end}" if include_time else ""
    if isinstance(entry, TranscriptSegment):
        speaker = f"（{entry.speaker_label}）" if entry.speaker_label else ""
        return f"[{entry.id}{time_str}] 台词{speaker}：{entry.text}"
    content = "；".join(_content_lines(entry))
    return f"[{entry.id}{time_str}] {content}"


def _derive_covered_empty_spans(document: EvidenceDocument) -> list[tuple[int, int]]:
    """依据提取器使用的同一切片网格推导空切片，并合并相邻切片。"""
    covered = {(obs.start_ms, obs.end_ms) for obs in document.observations}
    merged: list[tuple[int, int]] = []
    for span in calculate_slices(document.episode_duration_ms):
        if span in covered:
            continue
        if merged and merged[-1][1] == span[0]:
            merged[-1] = (merged[-1][0], span[1])
        else:
            merged.append(span)
    return merged


def render_evidence_timeline(
    document: EvidenceDocument,
    specialist_type: InteractionType | str,
    derived_observations: Iterable[DerivedObservation] = (),
) -> str:
    """渲染基线与当前分支派生观察的可引用时间线。

    Args:
        document: 只读基线证据文档。
        specialist_type: 当前分支的互动类型。
        derived_observations: 当前分支派生观察。

    Returns:
        按时间排序的纯文本时间线。

    Raises:
        ValueError: 当证据或渲染参数不合法时抛出。
    """
    if not isinstance(document, EvidenceDocument):
        raise TypeError("document 必须是 EvidenceDocument")
    try:
        interaction_type = InteractionType(specialist_type)
    except (TypeError, ValueError) as exc:
        raise ValueError("specialist_type 必须是五类互动之一") from exc

    branch_derived = list(derived_observations)
    if any(not isinstance(item, DerivedObservation) for item in branch_derived):
        raise TypeError("derived_observations 必须只包含 DerivedObservation")
    # 只校验并渲染调用方传入的当前分支，外分支 D<n> 不会进入视图。
    try:
        validate_derived_observations(document, interaction_type, branch_derived)
    except ValueError as exc:
        raise ValueError(f"派生证据非法: {exc}") from exc

    transcripts = list(document.transcript_segments)
    observations: list[Observation | DerivedObservation] = [
        *document.observations,
        *branch_derived,
    ]
    # 每条观察只在一个最小包含台词下缩进展示；否则作为独立条目。
    parents: dict[str, TranscriptSegment] = {}
    for observation in observations:
        containing = [
            transcript
            for transcript in transcripts
            if transcript.start_ms <= observation.start_ms
            and observation.end_ms <= transcript.end_ms
        ]
        if containing:
            parents[observation.id] = min(
                containing,
                key=lambda item: (
                    item.end_ms - item.start_ms,
                    item.start_ms,
                    item.id,
                ),
            )

    top_level: list[TranscriptSegment | Observation | DerivedObservation] = [
        *transcripts,
        *(observation for observation in observations if observation.id not in parents),
    ]
    top_level.sort(key=lambda item: (item.start_ms, item.end_ms, item.id))

    blocks: list[tuple[int, int, list[str]]] = []
    for entry in top_level:
        entry_lines = [_entry_line(entry)]
        if isinstance(entry, TranscriptSegment):
            children = [
                observation
                for observation in observations
                if parents.get(observation.id) is entry
            ]
            children.sort(key=lambda item: (item.start_ms, item.end_ms, item.id))
            for child in children:
                same_span = _span(child) == _span(entry)
                entry_lines.append("  " + _entry_line(child, include_time=not same_span))
        blocks.append((entry.start_ms, 1, entry_lines))

    # 推导 covered_empty 状态行并与证据行按时间混合排序
    empty_spans = _derive_covered_empty_spans(document)
    for start, end in empty_spans:
        blocks.append(
            (start, 0, [f"[已覆盖、无可记录观察 start_ms={start} end_ms={end}]"])
        )

    blocks.sort(key=lambda item: (item[0], item[1], item[2][0]))
    return "\n".join(line for _, _, block in blocks for line in block)


__all__ = ["render_evidence_timeline"]
