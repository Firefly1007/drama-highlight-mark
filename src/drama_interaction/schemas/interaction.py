"""互动输出契约层模块。

定义播放器消费的五类即时互动数据载荷（payload）及最终互动外壳（FinalInteraction）。
互动类型与边看边聊情绪均使用外部 JSON 直接消费的字符串枚举。
"""

from enum import Enum
from typing import Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from drama_interaction.config import (
    DEFERRED_VOTE_MAX_OPTIONS,
    DEFERRED_VOTE_MIN_OPTIONS,
    INSTANT_VOTE_OPTIONS_COUNT,
)


class InteractionType(str, Enum):
    """V2 对外互动类型字符串枚举。"""

    EMOTION_BUTTON = "emotion_button"  # 情绪按钮。
    REPEAT_KEYLINE = "repeat_keyline"  # 跟读金句。
    INSTANT_VOTE = "instant_vote"  # 即时投票。
    DEFERRED_VOTE = "deferred_vote"  # 延时投票。
    SIDE_COMMENT = "side_comment"  # 边看边聊。


class CommentMood(str, Enum):
    """边看边聊（side_comment）确定性情绪类型枚举。"""

    ROAST = "roast"  # 吐槽。
    SHOCK = "shock"  # 震惊。
    LAUGH = "laugh"  # 爆笑。
    PRAISE = "praise"  # 点赞。
    SYMPATHY = "sympathy"  # 同情。
    DOUBT = "doubt"  # 质疑。


VALID_COMMENT_MOODS: set[str] = {mood.value for mood in CommentMood}


class EmotionButtonName(str, Enum):
    """情绪按钮对外使用的英文名称。"""

    COOL = "cool"
    LAUGH = "laugh"
    TOMATO = "tomato"
    PROTECT = "protect"
    PITY = "pity"
    SHIP = "ship"


class EmotionButtonPayload(BaseModel):
    """情绪按钮载荷数据模型。

    根据 button_id 英文名称约束对应的可选文案（text）与弹幕列表（danmaku）。

    button_id 配置规则：
    - cool（爽）: 可选 text, 可选 danmaku
    - laugh（笑）: 禁止 text, 可选 danmaku
    - tomato（丢番茄）: 可选 text, 可选 danmaku
    - protect（护住 TA）: 禁止 text, 禁止 danmaku
    - pity（心疼 TA）: 禁止 text, 禁止 danmaku
    - ship（磕到了）: 禁止 text, 可选 danmaku

    Attributes:
        button_id: 按钮英文名称。
        text: 提示文案（仅 cool、tomato 允许配置）。
        danmaku: 触发时发射的弹幕列表（cool、laugh、tomato、ship 允许配置）。
    """

    model_config = ConfigDict(extra="forbid")

    button_id: EmotionButtonName = Field(..., description="按钮英文名称")
    text: str | None = Field(default=None, description="可选文案（仅爽/丢番茄支持）")
    danmaku: list[str] | None = Field(default=None, description="可选弹幕列表")

    @field_validator("text")
    @classmethod
    def validate_text_not_blank(cls, v: str | None) -> str | None:
        """校验文案如果提供则不能全为空白。

        Args:
            v: 输入的文案。

        Returns:
            校验通过的文案。

        Raises:
            ValueError: 当文案全为空白字符时抛出。
        """
        if v is not None and not v.strip():
            raise ValueError("情绪按钮文案不能全为空白字符")
        return v

    @field_validator("danmaku")
    @classmethod
    def validate_danmaku_items(cls, v: list[str] | None) -> list[str] | None:
        """校验弹幕列表如果提供则不能为空列表且条目不能全为空白。

        Args:
            v: 输入的弹幕列表。

        Returns:
            校验通过的弹幕列表。

        Raises:
            ValueError: 当弹幕列表为空列表或包含空白字符项时抛出。
        """
        if v is not None:
            if len(v) == 0:
                raise ValueError("弹幕列表如果配置则不能为空列表")
            for item in v:
                if not item.strip():
                    raise ValueError("弹幕条目不能全为空白字符")
        return v

    @model_validator(mode="after")
    def validate_button_constraints(self) -> "EmotionButtonPayload":
        """根据 button_id 严格校验 text 和 danmaku 的允许性。

        Returns:
            校验通过的自身实例。

        Raises:
            ValueError: 当字段与 button_id 规则冲突时抛出。
        """
        # 校验 text 的按钮白名单。
        if self.button_id in (
            EmotionButtonName.LAUGH,
            EmotionButtonName.PROTECT,
            EmotionButtonName.PITY,
            EmotionButtonName.SHIP,
        ) and self.text is not None:
            raise ValueError(f"button_id={self.button_id} 不允许配置 text 字段")

        # 校验 danmaku 的按钮白名单。
        if self.button_id in (EmotionButtonName.PROTECT, EmotionButtonName.PITY) and self.danmaku is not None:
            raise ValueError(f"button_id={self.button_id} 不允许配置 danmaku 字段")

        return self


class RepeatKeylinePayload(BaseModel):
    """跟读金句载荷数据模型。

    承载需要用户跟读的精彩台词文本。

    Attributes:
        text: 待跟读的金句台词文本，不能为空。
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, description="金句台词文本")

    @field_validator("text")
    @classmethod
    def validate_text_not_blank(cls, v: str) -> str:
        """校验金句文本不能全为空白。

        Args:
            v: 输入金句文本。

        Returns:
            校验通过的文本。

        Raises:
            ValueError: 当文本为空白时抛出。
        """
        # 先拒绝空白金句。
        if not v.strip():
            raise ValueError("跟读金句文本不能全为空白字符")
        return v


class InstantVotePayload(BaseModel):
    """即时投票载荷数据模型。

    用于二选一观点表态投票，必须恰好包含 2 个选项。

    Attributes:
        question: 投票问题题干，不能为空。
        options: 投票选项列表，长度必须严格等于 2。
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, description="投票题干")
    options: list[str] = Field(..., description="投票选项列表（必须恰好2项）")

    @field_validator("question")
    @classmethod
    def validate_question_not_blank(cls, v: str) -> str:
        """校验题干不能全为空白。

        Args:
            v: 输入题干。

        Returns:
            校验通过的题干。

        Raises:
            ValueError: 当题干为空白时抛出。
        """
        if not v.strip():
            raise ValueError("即时投票题干不能全为空白字符")
        return v

    @field_validator("options")
    @classmethod
    def validate_options(cls, v: list[str]) -> list[str]:
        """校验即时投票选项数量与内容。

        Args:
            v: 输入选项列表。

        Returns:
            校验通过的选项列表。

        Raises:
            ValueError: 当选项数量不为 INSTANT_VOTE_OPTIONS_COUNT、存在空白选项或存在重复选项时抛出。
        """
        # 校验选项数量。
        if len(v) != INSTANT_VOTE_OPTIONS_COUNT:
            raise ValueError(
                f"即时投票选项数量必须严格等于 {INSTANT_VOTE_OPTIONS_COUNT}，当前为 {len(v)}"
            )
        for opt in v:
            if not opt.strip():
                raise ValueError("即时投票选项不能全为空白字符")
        # 校验选项去重。
        if v[0].strip() == v[1].strip():
            raise ValueError(f"即时投票选项不能重复: '{v[0].strip()}'")
        return v


class DeferredVotePayload(BaseModel):
    """延时投票（竞猜）载荷数据模型。

    包含 2-4 个选项。模型在生成侧固定将正确答案输出在 0 号位（options[0] 为正确答案，answer_id=0），
    后续渲染阶段再通过确定性随机函数打乱选项顺序并重映射 answer_id。

    Attributes:
        question: 竞猜问题题干，不能为空。
        options: 选项列表，长度必须在 2 至 4 之间。
        answer_id: 正确答案在 options 中的索引（生成侧固定为 0，渲染阶段重映射）。
        reveal_time: 揭晓时刻（毫秒），生成侧为 None，渲染阶段计算后回填。
        reveal_delay: 揭晓展示时长（毫秒），生成侧为 None，渲染阶段回填。
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, description="竞猜题干")
    options: list[str] = Field(
        ...,
        description=f"选项列表（{DEFERRED_VOTE_MIN_OPTIONS}-{DEFERRED_VOTE_MAX_OPTIONS}项）",
    )
    answer_id: StrictInt = Field(
        ...,
        ge=0,
        description="正确答案在 options 中的索引（生成侧固定为 0，渲染打乱后重映射）",
    )
    reveal_time: StrictInt | None = Field(
        default=None, ge=0, description="揭晓时刻（毫秒，渲染环节填入）"
    )
    reveal_delay: StrictInt | None = Field(
        default=None, gt=0, description="揭晓展示时长（毫秒，渲染环节填入）"
    )

    @field_validator("question")
    @classmethod
    def validate_question_not_blank(cls, v: str) -> str:
        """校验题干不能全为空白。

        Args:
            v: 输入题干。

        Returns:
            校验通过的题干。

        Raises:
            ValueError: 当题干为空白时抛出。
        """
        if not v.strip():
            raise ValueError("延时投票题干不能全为空白字符")
        return v

    @field_validator("options")
    @classmethod
    def validate_options_count_and_items(cls, v: list[str]) -> list[str]:
        """校验延时投票选项数量在 DEFERRED_VOTE_MIN_OPTIONS 到 DEFERRED_VOTE_MAX_OPTIONS 之间，且项不为空白且不重复。

        Args:
            v: 输入选项列表。

        Returns:
            校验通过的选项列表。

        Raises:
            ValueError: 当选项数量超出范围、存在空白选项或存在重复选项时抛出。
        """
        # 校验选项数量。
        if not (DEFERRED_VOTE_MIN_OPTIONS <= len(v) <= DEFERRED_VOTE_MAX_OPTIONS):
            raise ValueError(
                f"延时投票选项数量必须在 {DEFERRED_VOTE_MIN_OPTIONS} 到 "
                f"{DEFERRED_VOTE_MAX_OPTIONS} 之间，当前为 {len(v)}"
            )
        for opt in v:
            if not opt.strip():
                raise ValueError("延时投票选项不能全为空白字符")
        # 校验选项去重。
        stripped_options = [opt.strip() for opt in v]
        if len(set(stripped_options)) != len(stripped_options):
            raise ValueError(f"延时投票选项不能包含重复项: {v}")
        return v

    @model_validator(mode="after")
    def validate_answer_id_bounds(self) -> "DeferredVotePayload":
        """校验 answer_id 是否在 options 索引合法范围内。

        Returns:
            校验通过的自身实例。

        Raises:
            ValueError: 当 answer_id 越界时抛出。
        """
        # 校验答案索引。
        if self.answer_id >= len(self.options):
            raise ValueError(
                f"answer_id ({self.answer_id}) 超出 options 索引范围 [0, {len(self.options) - 1}]"
            )
        return self


class SideCommentPayload(BaseModel):
    """边看边聊载荷数据模型。

    用于在特定剧情节点插入弹幕式吐槽或评论，支持确定性情绪标签。

    Attributes:
        text: 评论文本内容，不能为空。
        mood: 必填小写情绪标签（roast/shock/laugh/praise/sympathy/doubt）。
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, description="评论文本内容")
    mood: CommentMood = Field(
        ...,
        description="必填小写情绪标签（roast/shock/laugh/praise/sympathy/doubt）",
    )

    @field_validator("text")
    @classmethod
    def validate_text_not_blank(cls, v: str) -> str:
        """校验评论文本不能全为空白。

        Args:
            v: 输入评论文本。

        Returns:
            校验通过的文本。

        Raises:
            ValueError: 当文本为空白时抛出。
        """
        if not v.strip():
            raise ValueError("边看边聊评论文本不能全为空白字符")
        return v


# 互动类型到载荷模型的映射。
INTERACTION_PAYLOAD_TYPES: dict[str, type[BaseModel]] = {
    InteractionType.EMOTION_BUTTON.value: EmotionButtonPayload,
    InteractionType.REPEAT_KEYLINE.value: RepeatKeylinePayload,
    InteractionType.INSTANT_VOTE.value: InstantVotePayload,
    InteractionType.DEFERRED_VOTE.value: DeferredVotePayload,
    InteractionType.SIDE_COMMENT.value: SideCommentPayload,
}


# 五类互动载荷联合类型。
InteractionPayload = Union[  # noqa: UP007
    EmotionButtonPayload,
    RepeatKeylinePayload,
    InstantVotePayload,
    DeferredVotePayload,
    SideCommentPayload,
]


class FinalInteraction(BaseModel):
    """播放器最终消费的互动项外壳模型。

    对应 docs/schema.md 定义的输出结构。

    Attributes:
        id: 输出数组内的自增序号（从 1 开始）。
        type: 五类互动之一的字符串类型。
        show_at: 弹出展示开始时刻（毫秒，非负整数）。
        duration_ms: 展示持续时长（毫秒，正整数）。
        payload: 具体的业务载荷对象。
    """

    model_config = ConfigDict(extra="forbid")

    id: StrictInt = Field(..., ge=1, description="最终输出数组内的 1-based 序号")
    type: InteractionType = Field(..., description="五类互动之一的字符串类型")
    show_at: StrictInt = Field(..., ge=0, description="展示开始时间（毫秒）")
    duration_ms: StrictInt = Field(..., gt=0, description="展示持续时间（毫秒）")
    payload: InteractionPayload = Field(..., description="五类互动载荷之一")

    @model_validator(mode="after")
    def validate_type_and_payload_consistency(self) -> "FinalInteraction":
        """校验字符串 type、payload 类型及最终揭晓时间的一致性。

        Returns:
            校验通过的自身实例。

        Raises:
            ValueError: 当 type 与 payload 类型不一致时抛出。
        """
        expected_model = INTERACTION_PAYLOAD_TYPES[self.type.value]

        # 校验载荷类型。
        if not isinstance(self.payload, expected_model):
            raise ValueError(
                f"type='{self.type.value}' "
                f"与 payload 类型 ({type(self.payload).__name__}) 不匹配，"
                f"预期为 {expected_model.__name__}"
            )

        if isinstance(self.payload, DeferredVotePayload):
            if self.payload.reveal_time is None:
                raise ValueError("最终 deferred_vote 必须提供 reveal_time")
            if self.payload.reveal_delay is None:
                raise ValueError("最终 deferred_vote 必须提供 reveal_delay")
            interaction_end = self.show_at + self.duration_ms
            if self.payload.reveal_time < interaction_end:
                raise ValueError(
                    f"reveal_time ({self.payload.reveal_time}) 不得早于互动展示结束时间 "
                    f"({interaction_end})"
                )

        return self
