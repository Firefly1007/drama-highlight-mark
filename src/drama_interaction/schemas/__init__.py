"""短剧即时互动生成工作流 V2 — 核心数据契约层导出。

本模块汇集并导出证据结构（evidence）、互动载荷与最终输出（interaction）、
以及生成专家候选（candidate）的核心模型与校验器。
"""

from drama_interaction.schemas.candidate import (
    VALID_SPECIALIST_TYPES,
    Abstention,
    Candidate,
    RevealAnchor,
    SpecialistResult,
    TriggerAnchor,
)
from drama_interaction.schemas.evidence import (
    WINDOW_SIZE_MS,
    EvidenceWindow,
    TranscriptSegment,
    validate_evidence_sequence,
)
from drama_interaction.schemas.interaction import (
    MOOD_INT_TO_STR,
    MOOD_STR_TO_INT,
    TYPE_INT_TO_STR,
    TYPE_STR_TO_INT,
    VALID_COMMENT_MOODS,
    CommentMood,
    DeferredVotePayload,
    EmotionButtonPayload,
    FinalInteraction,
    InstantVotePayload,
    InteractionPayload,
    InteractionType,
    RepeatKeylinePayload,
    SideCommentPayload,
)

__all__ = [
    # 证据相关
    "WINDOW_SIZE_MS",
    "TranscriptSegment",
    "EvidenceWindow",
    "validate_evidence_sequence",
    # 互动与输出相关
    "InteractionType",
    "CommentMood",
    "TYPE_STR_TO_INT",
    "TYPE_INT_TO_STR",
    "MOOD_STR_TO_INT",
    "MOOD_INT_TO_STR",
    "VALID_COMMENT_MOODS",
    "EmotionButtonPayload",
    "RepeatKeylinePayload",
    "InstantVotePayload",
    "DeferredVotePayload",
    "SideCommentPayload",
    "InteractionPayload",
    "FinalInteraction",
    # 候选与专家输出相关
    "VALID_SPECIALIST_TYPES",
    "TriggerAnchor",
    "RevealAnchor",
    "Candidate",
    "Abstention",
    "SpecialistResult",
]
