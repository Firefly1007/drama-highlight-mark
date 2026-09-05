"""锚点解析、确定性渲染和全局约束。"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from drama_interaction.config import (
    DEFAULT_DEFERRED_VOTE_DURATION_MS,
    DEFAULT_EMOTION_BUTTON_DURATION_MS,
    DEFAULT_INSTANT_VOTE_DURATION_MS,
    DEFAULT_REVEAL_DISPLAY_MS,
    DEFAULT_REVEAL_GAP_MIN_MS,
    DEFAULT_SIDE_COMMENT_DURATION_MS,
    KEYLINE_DURATION_CEIL,
    KEYLINE_DURATION_FLOOR,
    KEYLINE_TAIL_MS,
    Settings,
)
from drama_interaction.schemas.candidate import (
    Candidate,
    RevealAnchor,
    TriggerAnchor,
)
from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    visible_evidence_entries,
)
from drama_interaction.schemas.interaction import DeferredVotePayload, FinalInteraction

# 固定命名空间保证相同 execution_id/candidate_id 的选项顺序可复现。
PROJECT_NAMESPACE = UUID("f8f7f6f5-f4f3-f2f1-f0ef-eeeeeeeeeeee")


@dataclass(frozen=True, slots=True)
class AnchorResolution:
    """锚点对应的证据标识和半开时间跨度。"""

    evidence_id: str
    start_ms: int
    end_ms: int


class ConstraintIssue(BaseModel):
    """一条确定性约束错误或淘汰原因。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    candidate_ids: tuple[str, ...] = ()
    route: str = "drop"


class ConstraintsReport(BaseModel):
    """确定性约束分析结果。"""

    model_config = ConfigDict(extra="forbid")

    eligible: list[FinalInteraction] = Field(default_factory=list)
    invalid: list[ConstraintIssue] = Field(default_factory=list)
    conflict_groups: list[tuple[str, ...]] = Field(default_factory=list)


def resolve_anchor(
    anchor: TriggerAnchor | RevealAnchor,
    document: EvidenceDocument,
    specialist_type: str,
    derived_observations: Sequence[DerivedObservation] = (),
) -> AnchorResolution:
    """按 transcript 优先规则解析当前分支的触发或揭晓锚点。"""

    entries = visible_evidence_entries(document, specialist_type, derived_observations)
    selected = anchor.transcript_segment_id or anchor.observation_id
    entry = entries.get(selected)
    if entry is None:
        raise ValueError(f"锚点引用的证据 {selected} 不存在于当前分支")
    return AnchorResolution(
        evidence_id=selected,
        start_ms=entry.start_ms,
        end_ms=entry.end_ms,
    )


def _duration_for(
    candidate: Candidate,
    trigger: AnchorResolution,
    config: Settings | None,
) -> int:
    """按互动类型计算最终展示时长。"""

    if candidate.specialist_type == "emotion_button":
        return (
            config.emotion_button_duration_ms
            if config is not None
            else DEFAULT_EMOTION_BUTTON_DURATION_MS
        )
    if candidate.specialist_type == "repeat_keyline":
        tail = config.keyline_tail_ms if config is not None else KEYLINE_TAIL_MS
        # 金句时长由证据跨度推导，并限制在播放器可接受范围内。
        return max(
            KEYLINE_DURATION_FLOOR,
            min(KEYLINE_DURATION_CEIL, trigger.end_ms - trigger.start_ms + tail),
        )
    if candidate.specialist_type == "instant_vote":
        return (
            config.instant_vote_duration_ms
            if config is not None
            else DEFAULT_INSTANT_VOTE_DURATION_MS
        )
    if candidate.specialist_type == "deferred_vote":
        return (
            config.deferred_vote_duration_ms
            if config is not None
            else DEFAULT_DEFERRED_VOTE_DURATION_MS
        )
    return (
        config.side_comment_duration_ms
        if config is not None
        else DEFAULT_SIDE_COMMENT_DURATION_MS
    )


def _shuffle_deferred_payload(
    payload: DeferredVotePayload,
    *,
    execution_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    """以 UUIDv5 派生局部种子打乱选项并重映射答案索引。"""

    if not execution_id.strip() or not candidate_id.strip():
        raise ValueError("deferred_vote 渲染需要非空 execution_id 和 candidate_id")
    indices = list(range(len(payload.options)))
    # UUIDv5 是唯一种子来源，不使用进程随机状态或 Python hash。
    seed = uuid5(PROJECT_NAMESPACE, f"{execution_id}:{candidate_id}")
    random.Random(seed.int).shuffle(indices)
    return {
        "question": payload.question,
        "options": [payload.options[index] for index in indices],
        "answer_id": indices.index(payload.answer_id),
        "reveal_time": payload.reveal_time,
        "reveal_delay": payload.reveal_delay,
    }


def render_candidate(
    candidate: Candidate,
    document: EvidenceDocument,
    derived_observations: Sequence[DerivedObservation] = (),
    *,
    execution_id: str,
    config: Settings | None = None,
) -> FinalInteraction:
    """将一个已入池候选渲染为最终互动对象。"""

    if candidate.candidate_id is None:
        raise ValueError("候选必须在渲染前拥有 candidate_id")
    trigger = resolve_anchor(
        candidate.trigger_anchor,
        document,
        candidate.specialist_type,
        derived_observations,
    )
    duration_ms = _duration_for(candidate, trigger, config)
    payload = candidate.payload.model_dump(mode="python")
    if candidate.specialist_type == "deferred_vote":
        reveal = resolve_anchor(
            candidate.reveal_anchor,
            document,
            candidate.specialist_type,
            derived_observations,
        )
        reveal_gap = (
            config.reveal_gap_min_ms
            if config is not None
            else DEFAULT_REVEAL_GAP_MIN_MS
        )
        if reveal.start_ms < trigger.start_ms + duration_ms + reveal_gap:
            raise ValueError("deferred_vote 的 reveal_anchor 不满足最小揭晓间隔")
        payload = _shuffle_deferred_payload(
            candidate.payload,
            execution_id=execution_id,
            candidate_id=candidate.candidate_id,
        )
        payload["reveal_time"] = reveal.start_ms
        payload["reveal_delay"] = (
            config.reveal_display_ms
            if config is not None
            else DEFAULT_REVEAL_DISPLAY_MS
        )
    return FinalInteraction(
        id=1,
        type=candidate.specialist_type,
        show_at=trigger.start_ms,
        duration_ms=duration_ms,
        payload=payload,
    )


def _interval(value: FinalInteraction) -> tuple[int, int]:
    """返回最终互动的半开展示区间。"""

    return value.show_at, value.show_at + value.duration_ms


def intervals_conflict(first: FinalInteraction, second: FinalInteraction) -> bool:
    """按半开区间判断两个展示区间是否相交。"""

    first_start, first_end = _interval(first)
    second_start, second_end = _interval(second)
    # 端点相等表示相邻，不是重叠；其余任意交集都算冲突。
    return first_start < second_end and second_start < first_end


def conflict_pairs(interactions: Sequence[FinalInteraction]) -> list[tuple[int, int]]:
    """返回所有相交互动的索引对。"""

    # ponytail: 候选池规模小，O(n²) 扫描最短且清晰；规模变大时再换区间索引。
    return [
        (left, right)
        for left in range(len(interactions))
        for right in range(left + 1, len(interactions))
        if intervals_conflict(interactions[left], interactions[right])
    ]


def _issue(
    code: str,
    message: str,
    *candidate_ids: str,
    route: str = "drop",
) -> ConstraintIssue:
    """构造定位明确的约束问题。"""

    return ConstraintIssue(
        code=code,
        message=message,
        candidate_ids=tuple(candidate_ids),
        route=route,
    )


def validate_final_interactions(
    interactions: Sequence[FinalInteraction],
    *,
    episode_duration_ms: int | None = None,
    config: Settings | None = None,
) -> list[ConstraintIssue]:
    """终检最终互动并返回所有可定位的确定性错误。"""

    errors: list[ConstraintIssue] = []
    identifiers: dict[int, int] = {}
    for index, interaction in enumerate(interactions):
        if interaction.id in identifiers:
            errors.append(
                _issue(
                    "duplicate_id",
                    f"互动 id {interaction.id} 重复",
                    str(interaction.id),
                    route="hitl",
                )
            )
        else:
            identifiers[interaction.id] = index

    expected_ids = list(range(1, len(interactions) + 1))
    actual_ids = [interaction.id for interaction in interactions]
    if actual_ids != expected_ids:
        errors.append(
            _issue(
                "id_sequence_invalid",
                "最终互动 id 必须按输出顺序从 1 连续递增",
                *(str(identifier) for identifier in actual_ids),
                route="hitl",
            )
        )

    budget = config.interaction_budget if config is not None else None
    if budget is not None and len(interactions) > int(budget):
        errors.append(
            _issue(
                "budget_exceeded",
                f"互动数量 {len(interactions)} 超过预算 {budget}",
                *(str(interaction.id) for interaction in interactions),
                route="hitl",
            )
        )

    spacing = config.min_interaction_spacing_ms if config is not None else None
    cooldowns = config.type_cooldown_ms if config is not None else {}

    for index, interaction in enumerate(interactions):
        end = interaction.show_at + interaction.duration_ms
        if episode_duration_ms is not None and end > episode_duration_ms:
            errors.append(
                _issue("outside_episode", f"互动 {interaction.id} 超出本集范围", str(interaction.id))
            )
        if isinstance(interaction.payload, DeferredVotePayload):
            reveal_gap = (
                config.reveal_gap_min_ms
                if config is not None
                else DEFAULT_REVEAL_GAP_MIN_MS
            )
            if interaction.payload.reveal_time < end + reveal_gap:
                errors.append(
                    _issue(
                        "reveal_gap_invalid",
                        f"互动 {interaction.id} 的揭晓间隔不足",
                        str(interaction.id),
                    )
                )
        if index:
            previous = interactions[index - 1]
            if spacing is not None and (
                interaction.show_at - (previous.show_at + previous.duration_ms)
                < int(spacing)
            ):
                errors.append(
                    _issue(
                        "spacing_invalid",
                        f"互动 {previous.id} 与 {interaction.id} 的间隔不足",
                        str(previous.id),
                        str(interaction.id),
                        route="hitl",
                    )
                )

    for left, right in conflict_pairs(interactions):
        errors.append(
            _issue(
                "interval_conflict",
                f"互动 {interactions[left].id} 与 {interactions[right].id} 的展示区间相交",
                str(interactions[left].id),
                str(interactions[right].id),
                route="semantic",
            )
        )

    # 终检拒绝同一互动被重复渲染；不以模型分数做隐式取舍。
    for left in range(len(interactions)):
        for right in range(left + 1, len(interactions)):
            first, second = interactions[left], interactions[right]
            if (
                first.type == second.type
                and first.show_at == second.show_at
                and first.duration_ms == second.duration_ms
                and first.payload.model_dump(mode="json")
                == second.payload.model_dump(mode="json")
            ):
                errors.append(
                    _issue(
                        "duplicate_interaction",
                        f"互动 {first.id} 与 {second.id} 内容重复",
                        str(first.id),
                        str(second.id),
                    )
                )

    for left in range(len(interactions)):
        for right in range(left + 1, len(interactions)):
            first, second = interactions[left], interactions[right]
            if first.type != second.type:
                continue
            cooldown = int(cooldowns.get(first.type.value, 0)) if cooldowns else 0
            if cooldown and abs(second.show_at - first.show_at) < cooldown:
                errors.append(
                    _issue(
                        "cooldown_invalid",
                        f"类型 {first.type.value} 的冷却时间不足",
                        str(first.id),
                        str(second.id),
                        route="hitl",
                    )
                )
    return errors


def analyze_constraints(
    interactions_by_candidate: Mapping[str, FinalInteraction],
    *,
    episode_duration_ms: int | None = None,
    config: Settings | None = None,
) -> ConstraintsReport:
    """分析确定性规则并仅把真实展示冲突交给语义调度。"""

    if any(
        not isinstance(candidate_id, str) or not candidate_id.strip()
        for candidate_id in interactions_by_candidate
    ):
        raise ValueError("candidate_id 必须是非空字符串")
    interactions = list(interactions_by_candidate.values())
    errors = validate_final_interactions(
        interactions,
        episode_duration_ms=episode_duration_ms,
        config=config,
    )
    interaction_to_candidate = {
        interaction.id: candidate_id
        for candidate_id, interaction in interactions_by_candidate.items()
    }
    invalid_ids: set[str] = set()
    remapped_errors: list[ConstraintIssue] = []
    for error in errors:
        ids = tuple(
            interaction_to_candidate.get(int(value), value)
            for value in error.candidate_ids
        )
        remapped = error.model_copy(update={"candidate_ids": ids})
        remapped_errors.append(remapped)
        if error.code != "interval_conflict":
            if error.route != "drop":
                continue
            invalid_ids.update(ids)

    eligible_pairs = [
        (candidate_id, interaction)
        for candidate_id, interaction in interactions_by_candidate.items()
        if candidate_id not in invalid_ids
    ]
    eligible = [interaction for _, interaction in eligible_pairs]
    groups: list[tuple[str, ...]] = []
    for left, right in conflict_pairs(eligible):
        pair = (eligible_pairs[left][0], eligible_pairs[right][0])
        groups.append(pair)
    return ConstraintsReport(
        eligible=eligible,
        invalid=[error for error in remapped_errors if error.code != "interval_conflict"],
        conflict_groups=groups,
    )


def assert_final_interactions(
    interactions: Sequence[FinalInteraction],
    *,
    episode_duration_ms: int | None = None,
    config: Settings | None = None,
) -> list[FinalInteraction]:
    """终检失败时抛出 ``ValueError``，成功时返回原列表副本。"""

    errors = validate_final_interactions(
        interactions,
        episode_duration_ms=episode_duration_ms,
        config=config,
    )
    if errors:
        raise ValueError("; ".join(error.message for error in errors))
    return list(interactions)


__all__ = [
    "AnchorResolution",
    "ConstraintIssue",
    "ConstraintsReport",
    "PROJECT_NAMESPACE",
    "analyze_constraints",
    "assert_final_interactions",
    "conflict_pairs",
    "intervals_conflict",
    "render_candidate",
    "resolve_anchor",
    "validate_final_interactions",
]
