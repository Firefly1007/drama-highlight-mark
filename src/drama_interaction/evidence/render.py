"""把当前 Specialist 可见证据渲染为可复制的时间线文本。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from drama_interaction.config import DEFAULT_MIN_REPORTED_GAP_MS
from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    Observation,
    TranscriptSegment,
    validate_derived_observations,
)
from drama_interaction.schemas.interaction import InteractionType


def _timecode(milliseconds: int) -> str:
    """把毫秒格式化为 ``HH:MM:SS.mmm``。"""
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


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
    time = f" {_timecode(start)}–{_timecode(end)}" if include_time else ""
    if isinstance(entry, TranscriptSegment):
        speaker = f"（{entry.speaker_label}）" if entry.speaker_label else ""
        return f"[{entry.id}]{time} 台词{speaker}：{entry.text}"
    content = "；".join(_content_lines(entry))
    return f"[{entry.id}]{time} {content}"


def render_evidence_timeline(
    document: EvidenceDocument,
    specialist_type: InteractionType | str,
    derived_observations: Iterable[DerivedObservation] = (),
    min_reported_gap_ms: int = DEFAULT_MIN_REPORTED_GAP_MS,
) -> str:
    """渲染基线与当前分支派生观察的可引用时间线。

    Args:
        document: 只读基线证据文档。
        specialist_type: 当前分支的互动类型。
        derived_observations: 当前分支派生观察。
        min_reported_gap_ms: 输出未覆盖区间的最小跨度。

    Returns:
        按时间排序的纯文本时间线。

    Raises:
        ValueError: 当证据或渲染参数不合法时抛出。
    """
    if not isinstance(document, EvidenceDocument):
        raise TypeError("document 必须是 EvidenceDocument")
    if type(min_reported_gap_ms) is not int or min_reported_gap_ms <= 0:
        raise ValueError("min_reported_gap_ms 必须为正整数")
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

    # 只用顶层条目计算覆盖；缩进观察已经由父台词覆盖。
    coverage = sorted((_span(entry) for entry in top_level), key=lambda item: item[0])
    merged: list[list[int]] = []
    for start, end in coverage:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    gaps: list[tuple[int, int]] = []
    cursor = 0
    for start, end in merged:
        if start - cursor >= min_reported_gap_ms:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if document.episode_duration_ms - cursor >= min_reported_gap_ms:
        gaps.append((cursor, document.episode_duration_ms))

    for start, end in gaps:
        blocks.append(
            (start, 0, [f"[未覆盖 {_timecode(start)}–{_timecode(end)}]"])
        )
    blocks.sort(key=lambda item: (item[0], item[1], item[2][0]))
    return "\n".join(line for _, _, block in blocks for line in block)


__all__ = [
    "render_evidence_timeline",
]
