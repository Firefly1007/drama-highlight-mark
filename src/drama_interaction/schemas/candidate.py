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

from drama_interaction.schemas.interaction import (
    TYPE_STR_TO_INT,
    DeferredVotePayload,
    EmotionButtonPayload,
    InstantVotePayload,
    InteractionPayload,
    RepeatKeylinePayload,
    SideCommentPayload,
)

# 允许的生成专家类型列表
VALID_SPECIALIST_TYPES: set[str] = set(TYPE_STR_TO_INT.keys())


class TriggerAnchor(BaseModel):
    """触发锚点数据模型。

    指向触发互动呈现的证据位置。

    Attributes:
        window_id: 所在的 3 秒证据窗口编号（必填）。
        transcript_segment_id: 关联的精确台词片段标识符（可选；纯视觉/音频证据时为空）。
    """

    model_config = ConfigDict(extra="forbid")

    window_id: int = Field(..., ge=0, description="证据窗口编号")
    transcript_segment_id: str | None = Field(
        default=None, description="可选台词片段标识符"
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


class RevealAnchor(BaseModel):
    """揭晓锚点数据模型（仅限 deferred_vote 延时投票使用）。

    指向延时投票公布答案或剧情揭晓的证据位置。

    Attributes:
        window_id: 揭晓所在的 3 秒证据窗口编号（必填）。
        transcript_segment_id: 关联的精确台词片段标识符（可选）。
    """

    model_config = ConfigDict(extra="forbid")

    window_id: int = Field(..., ge=0, description="揭晓证据窗口编号")
    transcript_segment_id: str | None = Field(
        default=None, description="可选台词片段标识符"
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


class Candidate(BaseModel):
    """生成专家输出的互动候选数据模型。

    进入候选池（Candidate Pool）前的标准化对象。
    严格禁止携带任何置信度/概率/评分字段（ADR-012），且生成侧禁止输出毫秒值（ADR-023）。

    Attributes:
        candidate_id: 候选唯一标识符（LLM 输出时为空，汇入 Candidate Pool 时程序赋值）。
        specialist_type: 生成该候选的专家类型（五类之一）。
        evidence_window_ids: 该候选依赖支撑的所有证据窗口编号列表。
        trigger_anchor: 触发锚点。
        payload: 对应互动类型的业务载荷对象。
        reveal_anchor: 揭晓锚点（仅 deferred_vote 延时投票要求且允许存在）。
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str | None = Field(
        default=None, description="候选ID（程序入池时生成）"
    )
    specialist_type: str = Field(..., description="专家类型名称")
    evidence_window_ids: list[int] = Field(
        ..., min_length=1, description="支撑该候选的所有证据窗口编号列表"
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

    @field_validator("evidence_window_ids")
    @classmethod
    def validate_window_ids_non_negative(cls, v: list[int]) -> list[int]:
        """校验证据窗口编号必须非负、非空且无重复。

        Args:
            v: 证据窗口编号列表。

        Returns:
            校验通过的窗口编号列表。

        Raises:
            ValueError: 当列表为空、包含负数窗口编号或包含重复窗口编号时抛出。
        """
        if not v:
            raise ValueError("evidence_window_ids 不能为空列表")
        for wid in v:
            if wid < 0:
                raise ValueError(f"evidence_window_ids 包含非法负数窗口编号: {wid}")
        if len(set(v)) != len(v):
            raise ValueError(f"evidence_window_ids 包含重复的窗口编号: {v}")
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
        if isinstance(data, dict):
            stype = data.get("specialist_type")
            payload_data = data.get("payload")

            # 零毫秒禁令静默清洗（ADR-023）：若生成侧提供了 reveal 毫秒字段，静默重置为 None
            if stype == "deferred_vote":
                if isinstance(payload_data, dict):
                    payload_data["reveal_time"] = None
                    payload_data["reveal_delay"] = None
                elif isinstance(payload_data, DeferredVotePayload):
                    if (
                        payload_data.reveal_time is not None
                        or payload_data.reveal_delay is not None
                    ):
                        payload_data = payload_data.model_copy(
                            update={"reveal_time": None, "reveal_delay": None}
                        )
                        data["payload"] = payload_data

            if isinstance(payload_data, dict) and stype in VALID_SPECIALIST_TYPES:
                if stype == "emotion_button":
                    data["payload"] = EmotionButtonPayload(**payload_data)
                elif stype == "repeat_keyline":
                    data["payload"] = RepeatKeylinePayload(**payload_data)
                elif stype == "instant_vote":
                    data["payload"] = InstantVotePayload(**payload_data)
                elif stype == "deferred_vote":
                    data["payload"] = DeferredVotePayload(**payload_data)
                elif stype == "side_comment":
                    data["payload"] = SideCommentPayload(**payload_data)
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

            # 揭晓窗口不得早于触发窗口
            if self.reveal_anchor.window_id < self.trigger_anchor.window_id:
                raise ValueError(
                    f"揭晓窗口 ({self.reveal_anchor.window_id}) "
                    f"不能早于触发窗口 ({self.trigger_anchor.window_id})"
                )

            # 生成侧零毫秒静默清洗兜底（确保实例上的 reveal 毫秒字段始终为 None）
            if isinstance(self.payload, DeferredVotePayload):
                if (
                    self.payload.reveal_time is not None
                    or self.payload.reveal_delay is not None
                ):
                    object.__setattr__(
                        self,
                        "payload",
                        self.payload.model_copy(
                            update={"reveal_time": None, "reveal_delay": None}
                        ),
                    )
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
