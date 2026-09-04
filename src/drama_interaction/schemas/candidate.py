"""生成专家输出与候选契约层模块。

定义生成专家（Specialist）输出侧的核心数据模型：
触发锚点（TriggerAnchor）、揭晓锚点（RevealAnchor）、候选对象（Candidate）、
弃权记录（Abstention）以及专家汇总结果（SpecialistResult）。
遵循 ADR-011 / ADR-012 / ADR-023：零毫秒、零置信度、锚点引用与严格类型校验。
"""

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from drama_interaction.schemas.evidence import (
    DerivedObservationId,
    EvidenceId,
    ObservationId,
    TranscriptId,
)
from drama_interaction.schemas.interaction import (
    DeferredVotePayload,
    EmotionButtonPayload,
    InstantVotePayload,
    InteractionPayload,
    InteractionType,
    RepeatKeylinePayload,
    SideCommentPayload,
)

# 允许的生成专家类型列表
VALID_SPECIALIST_TYPES: set[str] = {
    interaction_type.value for interaction_type in InteractionType
}


class TriggerAnchor(BaseModel):
    """触发锚点数据模型。

    指向触发互动呈现的证据位置。

    Attributes:
        transcript_segment_id: 台词片段标识符 T<n>（可选）。
        observation_id: 基线或派生观察标识符 O<n>/D<n>（可选）。
    """

    model_config = ConfigDict(extra="forbid")

    transcript_segment_id: TranscriptId | None = Field(
        default=None, description="可选台词片段标识符"
    )
    observation_id: ObservationId | DerivedObservationId | None = Field(
        default=None, description="可选观察标识符"
    )

    @field_validator("transcript_segment_id")
    @classmethod
    def validate_segment_id_not_blank(cls, v: str | None) -> str | None:
        """校验如果提供台词标识则不能全为空白。

        Args:
            v: 输入的台词片段标识符。

        Returns:
            校验通过的标识符。

        Raises:
            ValueError: 当标识符全为空白时抛出。
        """
        if v is not None and not v.strip():
            raise ValueError("transcript_segment_id 不能全为空白字符")
        return v

    @field_validator("observation_id")
    @classmethod
    def validate_observation_id(cls, v: str | None) -> str | None:
        """校验观察标识若提供则不能全为空白。"""
        if v is not None and not v.strip():
            raise ValueError("observation_id 不能全为空白字符")
        return v

    @model_validator(mode="after")
    def validate_reference_present(self) -> "TriggerAnchor":
        """校验锚点至少引用一个证据标识。"""
        if self.transcript_segment_id is None and self.observation_id is None:
            raise ValueError("触发锚点至少需要 transcript_segment_id 或 observation_id")
        return self


class RevealAnchor(BaseModel):
    """揭晓锚点数据模型（仅限 deferred_vote 延时投票使用）。

    指向延时投票公布答案或剧情揭晓的证据位置。

    Attributes:
        transcript_segment_id: 台词片段标识符 T<n>（可选）。
        observation_id: 基线或派生观察标识符 O<n>/D<n>（可选）。
    """

    model_config = ConfigDict(extra="forbid")

    transcript_segment_id: TranscriptId | None = Field(
        default=None, description="可选台词片段标识符"
    )
    observation_id: ObservationId | DerivedObservationId | None = Field(
        default=None, description="可选观察标识符"
    )

    @field_validator("transcript_segment_id")
    @classmethod
    def validate_segment_id_not_blank(cls, v: str | None) -> str | None:
        """校验如果提供台词标识则不能全为空白。

        Args:
            v: 输入的台词片段标识符。

        Returns:
            校验通过的标识符。

        Raises:
            ValueError: 当标识符全为空白时抛出。
        """
        if v is not None and not v.strip():
            raise ValueError("transcript_segment_id 不能全为空白字符")
        return v

    @field_validator("observation_id")
    @classmethod
    def validate_observation_id(cls, v: str | None) -> str | None:
        """校验观察标识若提供则不能全为空白。"""
        if v is not None and not v.strip():
            raise ValueError("observation_id 不能全为空白字符")
        return v

    @model_validator(mode="after")
    def validate_reference_present(self) -> "RevealAnchor":
        """校验锚点至少引用一个证据标识。"""
        if self.transcript_segment_id is None and self.observation_id is None:
            raise ValueError("揭晓锚点至少需要 transcript_segment_id 或 observation_id")
        return self


class Candidate(BaseModel):
    """生成专家输出的互动候选数据模型。

    进入候选池（Candidate Pool）前的标准化对象。
    严格禁止携带任何置信度/概率/评分字段（ADR-012），且生成侧禁止输出毫秒值（ADR-023）。

    Attributes:
        candidate_id: 候选唯一标识符（LLM 输出时为空，汇入 Candidate Pool 时程序赋值）。
        specialist_type: 生成该候选的专家类型（五类之一）。
        evidence_ids: 支撑候选的 T<n>/O<n>/D<n> 证据标识列表。
        trigger_anchor: 触发锚点。
        payload: 对应互动类型的业务载荷对象。
        reveal_anchor: 揭晓锚点（仅 deferred_vote 延时投票要求且允许存在）。
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str | None = Field(
        default=None, description="候选ID（程序入池时生成）"
    )
    specialist_type: str = Field(..., description="专家类型名称")
    evidence_ids: list[EvidenceId] = Field(
        ..., min_length=1, description="支撑该候选的证据标识列表"
    )
    trigger_anchor: TriggerAnchor = Field(..., description="触发锚点")
    payload: InteractionPayload = Field(..., description="业务载荷对象")
    reveal_anchor: RevealAnchor | None = Field(
        default=None, description="揭晓锚点（仅 deferred_vote 允许且必需）"
    )

    @field_validator("candidate_id")
    @classmethod
    def validate_candidate_id_not_blank(cls, v: str | None) -> str | None:
        """校验候选标识符若提供则不能全为空白。

        Args:
            v: 输入的候选标识符。

        Returns:
            校验通过的候选标识符。

        Raises:
            ValueError: 当候选标识符全为空白时抛出。
        """
        if v is not None and not v.strip():
            raise ValueError("candidate_id 不能全为空白字符")
        return v

    @field_validator("specialist_type")
    @classmethod
    def validate_specialist_type_known(cls, v: str) -> str:
        """校验专家类型必须为五类之一。

        Args:
            v: 输入的专家类型字符串。

        Returns:
            校验通过的专家类型。

        Raises:
            ValueError: 当专家类型不在受支持集合内时抛出。
        """
        if v not in VALID_SPECIALIST_TYPES:
            raise ValueError(
                f"未知的 specialist_type: '{v}'，可选集合为 {sorted(VALID_SPECIALIST_TYPES)}"
            )
        return v

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, v: list[str]) -> list[str]:
        """校验证据标识必须合法、非空且无重复。

        Args:
            v: 证据标识列表。

        Returns:
            校验通过的证据标识列表。

        Raises:
            ValueError: 当列表为空、标识格式非法或包含重复标识时抛出。
        """
        if not v:
            raise ValueError("evidence_ids 不能为空列表")
        for evidence_id in v:
            if not evidence_id.strip():
                raise ValueError("evidence_ids 不能包含空白标识")
        if len(set(v)) != len(v):
            raise ValueError(f"evidence_ids 包含重复标识: {v}")
        return v

    @model_validator(mode="before")
    @classmethod
    def parse_payload_by_specialist_type(cls, data: Any) -> Any:
        """根据 specialist_type 自动解析 dict 格式的 payload 为对应强类型模型。

        Args:
            data: 输入的数据字典或模型对象。

        Returns:
            解析后的数据。
        """
        if not isinstance(data, dict):
            return data

        stype = data.get("specialist_type")
        payload_data = data.get("payload")
        payload_model = {
            "emotion_button": EmotionButtonPayload,
            "repeat_keyline": RepeatKeylinePayload,
            "instant_vote": InstantVotePayload,
            "deferred_vote": DeferredVotePayload,
            "side_comment": SideCommentPayload,
        }.get(stype)
        if isinstance(payload_data, dict) and payload_model is not None:
            parsed_data = dict(data)
            parsed_data["payload"] = payload_model.model_validate(payload_data)
            return parsed_data
        return data

    @model_validator(mode="after")
    def validate_candidate_invariants(self) -> "Candidate":
        """校验 Candidate 的类型约束、载荷匹配性、揭晓锚点及生成侧零毫秒状态。

        Returns:
            校验通过的自身实例。

        Raises:
            ValueError: 当载荷类型不匹配、reveal_anchor 缺失或越界时抛出。
        """
        # 1. 检查 payload 与 specialist_type 的对应关系
        type_to_model = {
            "emotion_button": EmotionButtonPayload,
            "repeat_keyline": RepeatKeylinePayload,
            "instant_vote": InstantVotePayload,
            "deferred_vote": DeferredVotePayload,
            "side_comment": SideCommentPayload,
        }
        expected_payload_cls = type_to_model[self.specialist_type]
        if not isinstance(self.payload, expected_payload_cls):
            raise ValueError(
                f"specialist_type='{self.specialist_type}' 与 payload 类型 "
                f"({type(self.payload).__name__}) 不匹配，预期为 {expected_payload_cls.__name__}"
            )

        # 2. 揭晓锚点（reveal_anchor）与类型的绑定约束
        if self.specialist_type == "deferred_vote":
            # 延时投票必须提供 reveal_anchor
            if self.reveal_anchor is None:
                raise ValueError("延时投票 (deferred_vote) 必须配置 reveal_anchor")

            if isinstance(self.payload, DeferredVotePayload):
                if self.payload.answer_id != 0:
                    raise ValueError("生成侧 deferred_vote 的 answer_id 必须固定为 0")
                if (
                    self.payload.reveal_time is not None
                    or self.payload.reveal_delay is not None
                ):
                    raise ValueError("生成侧 Candidate 不允许包含绝对揭晓时间字段")
        else:
            # 非延时投票绝对禁止配置 reveal_anchor
            if self.reveal_anchor is not None:
                raise ValueError(
                    f"仅 deferred_vote 允许配置 reveal_anchor，当前类型为 '{self.specialist_type}'"
                )

        return self


class Abstention(BaseModel):
    """专家弃权记录数据模型。

    记录专家在发现潜在互动可能但证据不足以安全生成时的离散弃权状态（ADR-012）。

    Attributes:
        specialist_type: 弃权的专家类型。
        reason: 离散弃权原因描述。
    """

    model_config = ConfigDict(extra="forbid")

    specialist_type: str = Field(..., description="专家类型名称")
    reason: str = Field(..., min_length=1, description="弃权原因描述")

    @field_validator("specialist_type")
    @classmethod
    def validate_specialist_type_known(cls, v: str) -> str:
        """校验弃权专家类型必须已知。

        Args:
            v: 专家类型字符串。

        Returns:
            校验通过的专家类型。

        Raises:
            ValueError: 当专家类型非法时抛出。
        """
        if v not in VALID_SPECIALIST_TYPES:
            raise ValueError(f"未知的 specialist_type: '{v}'")
        return v

    @field_validator("reason")
    @classmethod
    def validate_reason_not_blank(cls, v: str) -> str:
        """校验弃权原因不能全为空白。

        Args:
            v: 输入的原因。

        Returns:
            校验通过的原因。

        Raises:
            ValueError: 当原因为空白时抛出。
        """
        if not v.strip():
            raise ValueError("弃权原因不能全为空白字符")
        return v


class SpecialistResult(BaseModel):
    """单个生成专家的最终汇总输出数据模型。

    包含该专家产出的全部合法候选与弃权记录。
    全结构绝对无置信度/评分字段（ADR-012）。

    Attributes:
        specialist_type: 专家类型名称。
        candidates: 产出的候选列表。
        abstentions: 产出的弃权列表。
    """

    model_config = ConfigDict(extra="forbid")

    specialist_type: str = Field(..., description="专家类型名称")
    candidates: list[Candidate] = Field(
        default_factory=list, description="候选互动列表"
    )
    abstentions: list[Abstention] = Field(
        default_factory=list, description="弃权记录列表"
    )

    @field_validator("specialist_type")
    @classmethod
    def validate_specialist_type_known(cls, v: str) -> str:
        """校验专家类型必须合法。

        Args:
            v: 输入类型。

        Returns:
            校验通过的类型。

        Raises:
            ValueError: 当类型未知时抛出。
        """
        if v not in VALID_SPECIALIST_TYPES:
            raise ValueError(f"未知的 specialist_type: '{v}'")
        return v

    @model_validator(mode="after")
    def validate_items_match_specialist_type(self) -> "SpecialistResult":
        """校验所有 candidate 和 abstention 的 specialist_type 必须与自身一致。

        Returns:
            校验通过的自身实例。

        Raises:
            ValueError: 当包含其他专家的候选或弃权记录时抛出。
        """
        # 确保候选列表中的类型与专家自身一致
        for c in self.candidates:
            if c.specialist_type != self.specialist_type:
                raise ValueError(
                    f"SpecialistResult 类型为 '{self.specialist_type}'，"
                    f"但包含类型为 '{c.specialist_type}' 的 Candidate"
                )

        # 确保弃权记录中的类型与专家自身一致
        for a in self.abstentions:
            if a.specialist_type != self.specialist_type:
                raise ValueError(
                    f"SpecialistResult 类型为 '{self.specialist_type}'，"
                    f"但包含类型为 '{a.specialist_type}' 的 Abstention"
                )

        return self
