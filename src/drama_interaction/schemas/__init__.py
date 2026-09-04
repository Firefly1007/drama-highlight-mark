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
    DerivedObservation,
    EvidenceDocument,
    EvidenceProvenance,
    Observation,
    QuerySpan,
    TranscriptSegment,
    validate_derived_observations,
)
from drama_interaction.schemas.interaction import (
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
    "EvidenceDocument",
    "Observation",
    "TranscriptSegment",
    "DerivedObservation",
    "EvidenceProvenance",
    "QuerySpan",
    "validate_derived_observations",
    # 互动与输出相关
    "InteractionType",
    "CommentMood",
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
