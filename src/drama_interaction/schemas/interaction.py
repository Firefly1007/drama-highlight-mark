"""互动输出契约层模块。

定义播放器消费的五类即时互动数据载荷（payload）及最终互动外壳（FinalInteraction）。
提供类型字符串与数字映射权威定义、情绪标签枚举及严格的字段级约束校验。
"""

from enum import IntEnum
from typing import Any, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from drama_interaction.config import (
    DEFAULT_DEFERRED_VOTE_ANSWER_ID,
    DEFERRED_VOTE_MAX_OPTIONS,
    DEFERRED_VOTE_MIN_OPTIONS,
    EMOTION_BUTTON_MAX_ID,
    EMOTION_BUTTON_MIN_ID,
    INSTANT_VOTE_OPTIONS_COUNT,
)


class InteractionType(IntEnum):
    """权威互动类型枚举定义（数字映射沿用 V1 约定）。"""

    EMOTION_BUTTON = 1  # 情绪按钮
    REPEAT_KEYLINE = 2  # 跟读金句
    INSTANT_VOTE = 3  # 即时投票
    DEFERRED_VOTE = 4  # 延时投票
    SIDE_COMMENT = 5  # 边看边聊


# 互动类型字符串名称与整数编码的双向映射字典（唯一权威数据源）
TYPE_STR_TO_INT: dict[str, int] = {e.name.lower(): e.value for e in InteractionType}
TYPE_INT_TO_STR: dict[int, str] = {e.value: e.name.lower() for e in InteractionType}


class CommentMood(IntEnum):
    """边看边聊（side_comment）确定性情绪类型枚举。"""

    ROAST = 1  # 吐槽（离谱反差、降智行为、槽点）
    SHOCK = 2  # 震惊（反转、暴击、不可思议）
    LAUGH = 3  # 爆笑（搞笑、幽默、欢乐场面）
    PRAISE = 4  # 点赞（打脸爽点、高光反击、霸气）
    SYMPATHY = 5  # 同情（虐心、心疼、委屈泪点）
    DOUBT = 6  # 质疑（怀疑有诈、猜测真相、侦探视角）


# 边看边聊情绪选项与整数编码映射字典（由 CommentMood 自动派生）
MOOD_STR_TO_INT: dict[str, int] = {e.name.lower(): e.value for e in CommentMood}
MOOD_INT_TO_STR: dict[int, str] = {e.value: e.name.lower() for e in CommentMood}
VALID_COMMENT_MOODS: set[str] = set(MOOD_STR_TO_INT.keys())


class EmotionButtonPayload(BaseModel):
    """情绪按钮载荷数据模型。

    根据 button_id（0-5）约束对应的可选文案（text）与弹幕列表（danmaku）。

    button_id 配置规则：
    - 0 (爽 / cool): 可选 text, 可选 danmaku
    - 1 (笑 / laugh): 禁止 text, 可选 danmaku
    - 2 (丢番茄 / tomato): 可选 text, 可选 danmaku
    - 3 (护住TA / protect): 禁止 text, 禁止 danmaku
    - 4 (心疼TA / pity): 禁止 text, 禁止 danmaku
    - 5 (磕到了 / ship): 禁止 text, 可选 danmaku

    Attributes:
        button_id: 按钮编号（0-5）。
        text: 提示文案（仅 0, 2 允许配置）。
        danmaku: 触发时发射的弹幕列表（0, 1, 2, 5 允许配置）。
    """

    model_config = ConfigDict(extra="forbid")

    button_id: int = Field(
        ...,
        ge=EMOTION_BUTTON_MIN_ID,
        le=EMOTION_BUTTON_MAX_ID,
        description=f"按钮编号（{EMOTION_BUTTON_MIN_ID}-{EMOTION_BUTTON_MAX_ID}）",
    )
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
        # button_id 1, 3, 4, 5 禁止配置 text
        if self.button_id in (1, 3, 4, 5) and self.text is not None:
            raise ValueError(f"button_id={self.button_id} 不允许配置 text 字段")

        # button_id 3, 4 禁止配置 danmaku（必须为 None）
        if self.button_id in (3, 4) and self.danmaku is not None:
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
        # 跟读文本不能为空
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
        # 即时投票严格要求 INSTANT_VOTE_OPTIONS_COUNT 个选项
        if len(v) != INSTANT_VOTE_OPTIONS_COUNT:
            raise ValueError(
                f"即时投票选项数量必须严格等于 {INSTANT_VOTE_OPTIONS_COUNT}，当前为 {len(v)}"
            )
        for opt in v:
            if not opt.strip():
                raise ValueError("即时投票选项不能全为空白字符")
        # 两个选项内容不能相同
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
    answer_id: int = Field(
        default=DEFAULT_DEFERRED_VOTE_ANSWER_ID,
        ge=0,
        description="正确答案在 options 中的索引（生成侧固定为 0，渲染打乱后重映射）",
    )
    reveal_time: int | None = Field(
        default=None, ge=0, description="揭晓时刻（毫秒，渲染环节填入）"
    )
    reveal_delay: int | None = Field(
        default=None, ge=0, description="揭晓展示时长（毫秒，渲染环节填入）"
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
        # 延时投票支持 DEFERRED_VOTE_MIN_OPTIONS 到 DEFERRED_VOTE_MAX_OPTIONS 个选项
        if not (DEFERRED_VOTE_MIN_OPTIONS <= len(v) <= DEFERRED_VOTE_MAX_OPTIONS):
            raise ValueError(
                f"延时投票选项数量必须在 {DEFERRED_VOTE_MIN_OPTIONS} 到 "
                f"{DEFERRED_VOTE_MAX_OPTIONS} 之间，当前为 {len(v)}"
            )
        for opt in v:
            if not opt.strip():
                raise ValueError("延时投票选项不能全为空白字符")
        # 检查选项是否存在重复项
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
        # 验证答案索引是否指向合法选项
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
        mood: 情绪标签字符串（可选，支持 roast/shock/laugh/praise/sympathy/doubt）。
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, description="评论文本内容")
    mood: str | None = Field(
        default=None,
        description="情绪标签（可选，支持 roast/shock/laugh/praise/sympathy/doubt）",
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

    @field_validator("mood")
    @classmethod
    def validate_mood_known(cls, v: str | None) -> str | None:
        """校验情绪标签若提供则必须在允许的选项内。

        Args:
            v: 输入情绪标签。

        Returns:
            校验通过的标准情绪标签。

        Raises:
            ValueError: 当情绪标签不在合法集合内时抛出。
        """
        if v is not None:
            v_norm = v.strip().lower()
            if v_norm not in VALID_COMMENT_MOODS:
                raise ValueError(
                    f"未知的 mood: '{v}'，可选集合为 {sorted(VALID_COMMENT_MOODS)}"
                )
            return v_norm
        return None


# 五类互动 Payload 的联合类型
InteractionPayload = Union[  # ruff: ignore[non-pep604-annotation-union]
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
        type: 互动类型数字（1-5）。
        show_at: 弹出展示开始时刻（毫秒，非负整数）。
        duration_ms: 展示持续时长（毫秒，正整数）。
        payload: 具体的业务载荷对象。
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., ge=1, description="最终输出数组内的 1-based 序号")
    type: int = Field(..., ge=1, le=5, description="互动类型数字（1-5）")
    show_at: int = Field(..., ge=0, description="展示开始时间（毫秒）")
    duration_ms: int = Field(..., gt=0, description="展示持续时间（毫秒）")
    payload: InteractionPayload = Field(..., description="五类互动载荷之一")

    @model_validator(mode="before")
    @classmethod
    def parse_payload_by_type(cls, data: Any) -> Any:
        """根据 type 自动将 dict 形式的 payload 解析为对应的 Payload 模型，并支持字符串类型转数字。

        Args:
            data: 输入的字典或模型数据。

        Returns:
            解析并装载好 payload 对象的输入数据。

        Raises:
            ValueError: 当 type 与 payload 结构不匹配或数据非法时抛出。
        """
        if isinstance(data, dict):
            raw_type = data.get("type")
            # 容错支持：如果传入的是类型字符串名（如 "emotion_button"），自动转为数字 1-5
            if isinstance(raw_type, str) and raw_type in TYPE_STR_TO_INT:
                data["type"] = TYPE_STR_TO_INT[raw_type]
                raw_type = data["type"]

            int_type = data.get("type")
            payload_data = data.get("payload")
            # 如果 payload 是 dict，且 type 明确，则显式转换为具体的 Payload 类
            if isinstance(payload_data, dict) and int_type is not None:
                if int_type == InteractionType.EMOTION_BUTTON.value:
                    data["payload"] = EmotionButtonPayload(**payload_data)
                elif int_type == InteractionType.REPEAT_KEYLINE.value:
                    data["payload"] = RepeatKeylinePayload(**payload_data)
                elif int_type == InteractionType.INSTANT_VOTE.value:
                    data["payload"] = InstantVotePayload(**payload_data)
                elif int_type == InteractionType.DEFERRED_VOTE.value:
                    data["payload"] = DeferredVotePayload(**payload_data)
                elif int_type == InteractionType.SIDE_COMMENT.value:
                    data["payload"] = SideCommentPayload(**payload_data)
        return data

    @model_validator(mode="after")
    def validate_type_and_payload_consistency(self) -> "FinalInteraction":
        """校验 type 数字与 payload 具体类型的严格一致性。

        Returns:
            校验通过的自身实例。

        Raises:
            ValueError: 当 type 与 payload 类型不一致时抛出。
        """
        type_to_model_map = {
            InteractionType.EMOTION_BUTTON.value: EmotionButtonPayload,
            InteractionType.REPEAT_KEYLINE.value: RepeatKeylinePayload,
            InteractionType.INSTANT_VOTE.value: InstantVotePayload,
            InteractionType.DEFERRED_VOTE.value: DeferredVotePayload,
            InteractionType.SIDE_COMMENT.value: SideCommentPayload,
        }

        expected_model = type_to_model_map.get(self.type)
        if expected_model is None:
            raise ValueError(f"未知的互动类型数字: {self.type}")

        # 检查 payload 是否为该类型对应的正确模型
        if not isinstance(self.payload, expected_model):
            raise ValueError(
                f"type={self.type} ({TYPE_INT_TO_STR.get(self.type)}) "
                f"与 payload 类型 ({type(self.payload).__name__}) 不匹配，"
                f"预期为 {expected_model.__name__}"
            )

        return self
