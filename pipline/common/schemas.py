import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_validator,
)

TIMESTAMP_PATTERN = r"^\d{2}:\d{2}:\d{2}\.\d{3}$"


class Segment(BaseModel):
    """描述单个音频切分片段的结构化信息。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    start: str = Field(pattern=TIMESTAMP_PATTERN)
    end: str = Field(pattern=TIMESTAMP_PATTERN)
    text: str = ""
    speech: str = ""
    emotion: str = ""
    voice: str = ""
    music: str = ""
    audio_cues: list[str] = Field(default_factory=list)
    uncertainty: str = ""

    @field_validator("start", "end", mode="before")
    @classmethod
    def normalize_timestamp(cls, value: str) -> str:
        """将 MM:SS.mmm 补全为 00:MM:SS.mmm，并校验 MM/SS/mmm 数值范围。"""
        if not isinstance(value, str):
            return value

        parts = value.split(":")
        if len(parts) == 2:
            value = f"00:{value}"
            parts = value.split(":")

        if len(parts) == 3:
            hh, mm, rest = parts
            if "." in rest:
                ss, mmm = rest.split(".", 1)
            else:
                ss, mmm = rest, "0"

            _ = hh
            mm_val, ss_val, mmm_val = int(mm), int(ss), int(mmm)
            if not (0 <= mm_val <= 59):
                raise ValueError(f"分钟值 {mm_val} 超出范围 00-59")
            if not (0 <= ss_val <= 59):
                raise ValueError(f"秒值 {ss_val} 超出范围 00-59")
            if not (0 <= mmm_val <= 999):
                raise ValueError(f"毫秒值 {mmm_val} 超出范围 000-999")

        return value


class SegmentsDocument(BaseModel):
    """表示包含多个音频片段的根文档结构。"""

    model_config = ConfigDict(extra="forbid")

    segments: list[Segment]

    @field_validator("segments")
    @classmethod
    def validate_segments(cls, value: list[Segment]) -> list[Segment]:
        """校验 segments 非空，自动修正不连续的 id。"""
        if not value:
            raise ValueError("segments 不能为空")

        for index, segment in enumerate(value, start=1):
            if segment.id != index:
                segment.id = index

        return value


class SegmentsList(RootModel[list[Segment]]):
    """表示以数组为根节点的音频片段列表。"""

    @field_validator("root")
    @classmethod
    def validate_root(cls, value: list[Segment]) -> list[Segment]:
        """校验根数组非空且片段 id 连续递增。"""
        if not value:
            raise ValueError("segments 不能为空")

        for index, segment in enumerate(value, start=1):
            if segment.id != index:
                raise ValueError(
                    f"第 {index} 个片段 id 应为 {index}，实际为 {segment.id}"
                )

        return value


class SemanticHighlightItem(BaseModel):
    """表示模型直接输出的最小语义高光结构。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    summary: str
    level: Literal[1, 2, 3]
    reason: str
    segment_ids: list[int]
    trigger_segment_id: int

    @field_validator("segment_ids")
    @classmethod
    def validate_segment_ids(cls, value: list[int]) -> list[int]:
        """校验高光证据片段 id 非空且升序。"""
        if not value:
            raise ValueError("segment_ids 不能为空")

        if value != sorted(value):
            raise ValueError("segment_ids 必须按升序排列")

        return value


class FinalHighlightItem(BaseModel):
    """表示最终落盘的单条高光数据。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    summary: str
    level: Literal[1, 2, 3]
    reason: str
    segment_ids: list[int]
    trigger_segment_id: int
    start: str = Field(pattern=TIMESTAMP_PATTERN)
    end: str = Field(pattern=TIMESTAMP_PATTERN)
    trigger_time: str = Field(pattern=TIMESTAMP_PATTERN)
    evidence_segments: list[Segment]

    @field_validator("segment_ids")
    @classmethod
    def validate_segment_ids(cls, value: list[int]) -> list[int]:
        """校验最终高光证据片段 id 非空且升序。"""
        if not value:
            raise ValueError("segment_ids 不能为空")

        if value != sorted(value):
            raise ValueError("segment_ids 必须按升序排列")

        return value


class HighlightsDocument(BaseModel):
    """表示模型返回的高光根文档结构。"""

    model_config = ConfigDict(extra="forbid")

    highlights: list[SemanticHighlightItem]

    @field_validator("highlights")
    @classmethod
    def validate_highlights(
        cls, value: list[SemanticHighlightItem]
    ) -> list[SemanticHighlightItem]:
        """校验高光 id 连续递增。"""
        for index, highlight in enumerate(value, start=1):
            if highlight.id != index:
                raise ValueError(
                    f"第 {index} 个高光 id 应为 {index}，实际为 {highlight.id}"
                )

        return value

    def validate_against_segments(self, segments: list[Segment]) -> list[FinalHighlightItem]:
        """交叉校验 highlights 与原始 segments，并补全最终输出字段。"""
        segment_map = {segment.id: segment for segment in segments}
        outputs: list[FinalHighlightItem] = []

        for index, highlight in enumerate(self.highlights, start=1):
            evidence_segments: list[Segment] = []
            for segment_id in highlight.segment_ids:
                segment = segment_map.get(segment_id)
                if segment is None:
                    raise ValueError(
                        f"第 {index} 个高光引用了不存在的 segment {segment_id}"
                    )
                evidence_segments.append(segment)

            if highlight.trigger_segment_id not in highlight.segment_ids:
                raise ValueError(
                    f"第 {index} 个高光的 trigger_segment_id "
                    f"{highlight.trigger_segment_id} 不在 segment_ids 中"
                )

            trigger_segment = segment_map[highlight.trigger_segment_id]
            outputs.append(
                FinalHighlightItem(
                    id=highlight.id,
                    summary=highlight.summary,
                    level=highlight.level,
                    reason=highlight.reason,
                    segment_ids=highlight.segment_ids,
                    trigger_segment_id=highlight.trigger_segment_id,
                    start=min(segment.start for segment in evidence_segments),
                    end=max(segment.end for segment in evidence_segments),
                    trigger_time=trigger_segment.start,
                    evidence_segments=evidence_segments,
                )
            )

        return outputs


class HighlightsList(RootModel[list[FinalHighlightItem]]):
    """表示以数组为根节点的最终高光列表。"""

    @field_validator("root")
    @classmethod
    def validate_root(cls, value: list[FinalHighlightItem]) -> list[FinalHighlightItem]:
        """校验高光 id 连续递增。"""
        for index, highlight in enumerate(value, start=1):
            if highlight.id != index:
                raise ValueError(
                    f"第 {index} 个高光 id 应为 {index}，实际为 {highlight.id}"
                )

        return value


EmotionButtonType = Literal["cool", "laugh", "tomato", "protect", "pity", "ship"]
EmotionButtonId = Literal[0, 1, 2, 3, 4, 5]

EMOTION_BUTTON_TYPE_TO_ID: dict[EmotionButtonType, EmotionButtonId] = {
    "cool": 0,
    "laugh": 1,
    "tomato": 2,
    "protect": 3,
    "pity": 4,
    "ship": 5,
}
EMOTION_BUTTON_ID_TO_TYPE: dict[EmotionButtonId, EmotionButtonType] = {
    button_id: type_name for type_name, button_id in EMOTION_BUTTON_TYPE_TO_ID.items()
}
EMOTION_BUTTON_TOP_LEVEL_TYPE = 1
REPEAT_KEYLINE_TOP_LEVEL_TYPE = 2
INSTANT_VOTE_TOP_LEVEL_TYPE = 3
DEFERRED_VOTE_TOP_LEVEL_TYPE = 4
SIDE_COMMENT_TOP_LEVEL_TYPE = 5
EMOTION_BUTTON_TEXT_MIN_CHARS = 2
EMOTION_BUTTON_TEXT_MAX_CHARS = 8
EMOTION_BUTTON_DANMAKU_MIN_ITEMS = 4
EMOTION_BUTTON_DANMAKU_MAX_ITEMS = 6
EMOTION_BUTTON_DANMAKU_MIN_CHARS = 4
EMOTION_BUTTON_DANMAKU_MAX_CHARS = 12
EMOTION_BUTTON_FORBIDDEN_TERMS = (
    "男主",
    "女主",
    "反派",
    "身份揭露",
    "强势宣言",
    "情绪转折",
    "反差笑点",
    "剧情推进",
)
EMOTION_BUTTON_FIELD_RULES = {
    "cool": {"text": True, "danmaku": True},
    "laugh": {"text": False, "danmaku": True},
    "tomato": {"text": True, "danmaku": True},
    "protect": {"text": False, "danmaku": False},
    "pity": {"text": False, "danmaku": False},
    "ship": {"text": False, "danmaku": True},
}


def count_text_characters(value: str) -> int:
    """统计字符串总字符数，标点符号也计入。"""
    return len(value)


def validate_emotion_button_copy_text(
    value: str,
    *,
    field_name: str,
    min_chars: int,
    max_chars: int,
) -> str:
    """校验 emotion_button 文案的总字符数和禁用词。"""
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空字符串")

    character_count = count_text_characters(text)
    if not (min_chars <= character_count <= max_chars):
        raise ValueError(
            f"{field_name} 需包含 {min_chars} 到 {max_chars} 个字符（含标点符号），当前为 {character_count}"
        )

    for term in EMOTION_BUTTON_FORBIDDEN_TERMS:
        if term in text:
            raise ValueError(f"{field_name} 不允许包含禁用词“{term}”")

    return text


class EmotionButtonModelPayload(BaseModel):
    """表示模型输出的 emotion_button payload。"""

    model_config = ConfigDict(extra="forbid")

    button_type: EmotionButtonType
    text: str | None = None
    danmaku: list[str] | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        """校验按钮文案非空、总字符数和禁用词。"""
        if value is None:
            return value

        return validate_emotion_button_copy_text(
            value,
            field_name="payload.text",
            min_chars=EMOTION_BUTTON_TEXT_MIN_CHARS,
            max_chars=EMOTION_BUTTON_TEXT_MAX_CHARS,
        )

    @field_validator("danmaku")
    @classmethod
    def validate_danmaku(cls, value: list[str] | None) -> list[str] | None:
        """校验预设弹幕条数、元素非空、总字符数和禁用词。"""
        if value is None:
            return value

        if not value:
            raise ValueError("payload.danmaku 不能为空数组")
        if not (
            EMOTION_BUTTON_DANMAKU_MIN_ITEMS
            <= len(value)
            <= EMOTION_BUTTON_DANMAKU_MAX_ITEMS
        ):
            raise ValueError(
                "payload.danmaku 条数需为 "
                f"{EMOTION_BUTTON_DANMAKU_MIN_ITEMS} 到 {EMOTION_BUTTON_DANMAKU_MAX_ITEMS} 条，"
                f"当前为 {len(value)} 条"
            )

        normalized: list[str] = []
        for index, item in enumerate(value, start=1):
            normalized.append(
                validate_emotion_button_copy_text(
                    item,
                    field_name=f"payload.danmaku 第 {index} 项",
                    min_chars=EMOTION_BUTTON_DANMAKU_MIN_CHARS,
                    max_chars=EMOTION_BUTTON_DANMAKU_MAX_CHARS,
                )
            )

        return normalized

    @model_validator(mode="after")
    def validate_field_combo(self) -> "EmotionButtonModelPayload":
        """按按钮类型校验 payload 字段组合。"""
        rules = EMOTION_BUTTON_FIELD_RULES[self.button_type]
        has_text = self.text is not None
        has_danmaku = self.danmaku is not None

        if rules["text"] and not has_text:
            raise ValueError(f"button_type={self.button_type} 时 payload.text 必填")
        if not rules["text"] and has_text:
            raise ValueError(
                f"button_type={self.button_type} 时 payload.text 不允许出现"
            )
        if rules["danmaku"] and not has_danmaku:
            raise ValueError(
                f"button_type={self.button_type} 时 payload.danmaku 必填"
            )
        if not rules["danmaku"] and has_danmaku:
            raise ValueError(
                f"button_type={self.button_type} 时 payload.danmaku 不允许出现"
            )

        return self


class EmotionButtonModelItem(BaseModel):
    """表示模型输出的单条 emotion_button 中间结果。"""

    model_config = ConfigDict(extra="forbid")

    highpoint_id: int = Field(ge=1)
    payload: EmotionButtonModelPayload


class EmotionButtonModelDocument(BaseModel):
    """表示模型输出的 emotion_button 根文档结构。"""

    model_config = ConfigDict(extra="forbid")

    interactions: list[EmotionButtonModelItem]

    @field_validator("interactions")
    @classmethod
    def validate_interactions(
        cls, value: list[EmotionButtonModelItem]
    ) -> list[EmotionButtonModelItem]:
        """校验同一 highpoint 最多只出现一次。"""
        highpoint_ids: set[int] = set()
        for item in value:
            if item.highpoint_id in highpoint_ids:
                raise ValueError(
                    f"highpoint_id={item.highpoint_id} 重复出现，同一 highpoint 最多只能生成 1 条 emotion_button"
                )
            highpoint_ids.add(item.highpoint_id)

        return value


class RepeatKeylineModelPayload(BaseModel):
    """表示模型输出的 repeat_keyline payload。"""

    model_config = ConfigDict(extra="forbid")

    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """校验复述台词非空。"""
        text = value.strip()
        if not text:
            raise ValueError("payload.text 不能为空字符串")
        return text


class RepeatKeylineModelItem(BaseModel):
    """表示模型输出的单条 repeat_keyline 中间结果。"""

    model_config = ConfigDict(extra="forbid")

    highpoint_id: int = Field(ge=1)
    payload: RepeatKeylineModelPayload


class RepeatKeylineModelDocument(BaseModel):
    """表示模型输出的 repeat_keyline 根文档结构。"""

    model_config = ConfigDict(extra="forbid")

    interactions: list[RepeatKeylineModelItem]

    @field_validator("interactions")
    @classmethod
    def validate_interactions(
        cls, value: list[RepeatKeylineModelItem]
    ) -> list[RepeatKeylineModelItem]:
        """校验同一 highpoint 最多只出现一次。"""
        highpoint_ids: set[int] = set()
        for item in value:
            if item.highpoint_id in highpoint_ids:
                raise ValueError(
                    f"highpoint_id={item.highpoint_id} 重复出现，同一 highpoint 最多只能生成 1 条 repeat_keyline"
                )
            highpoint_ids.add(item.highpoint_id)

        return value


class InstantVoteModelPayload(BaseModel):
    """表示模型输出的 instant_vote payload。"""

    model_config = ConfigDict(extra="forbid")

    question: str
    options: list[str]

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        """校验投票问题非空。"""
        text = value.strip()
        if not text:
            raise ValueError("payload.question 不能为空字符串")
        return text

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        """校验投票选项为 2 个非空字符串。"""
        if len(value) != 2:
            raise ValueError(f"payload.options 必须恰好包含 2 个元素，当前为 {len(value)} 个")

        normalized: list[str] = []
        for index, item in enumerate(value, start=1):
            text = item.strip()
            if not text:
                raise ValueError(f"payload.options 第 {index} 项不能为空字符串")
            normalized.append(text)

        return normalized


class InstantVoteModelItem(BaseModel):
    """表示模型输出的单条 instant_vote 中间结果。"""

    model_config = ConfigDict(extra="forbid")

    highpoint_id: int = Field(ge=1)
    payload: InstantVoteModelPayload


class InstantVoteModelDocument(BaseModel):
    """表示模型输出的 instant_vote 根文档结构。"""

    model_config = ConfigDict(extra="forbid")

    interactions: list[InstantVoteModelItem]

    @field_validator("interactions")
    @classmethod
    def validate_interactions(
        cls, value: list[InstantVoteModelItem]
    ) -> list[InstantVoteModelItem]:
        """校验同一 highpoint 最多只出现一次。"""
        highpoint_ids: set[int] = set()
        for item in value:
            if item.highpoint_id in highpoint_ids:
                raise ValueError(
                    f"highpoint_id={item.highpoint_id} 重复出现，同一 highpoint 最多只能生成 1 条 instant_vote"
                )
            highpoint_ids.add(item.highpoint_id)

        return value


class DeferredVoteModelPayload(BaseModel):
    """表示模型输出的 deferred_vote payload。"""

    model_config = ConfigDict(extra="forbid")

    question: str
    options: list[str]
    reveal_id: int = Field(ge=1)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        """校验延迟投票问题非空。"""
        text = value.strip()
        if not text:
            raise ValueError("payload.question 不能为空字符串")
        return text

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        """校验延迟投票选项为 2 到 4 个非空字符串。"""
        if not 2 <= len(value) <= 4:
            raise ValueError(
                f"payload.options 必须是 2 到 4 个元素的字符串数组，当前为 {len(value)} 个"
            )

        normalized: list[str] = []
        for index, item in enumerate(value, start=1):
            text = item.strip()
            if not text:
                raise ValueError(f"payload.options 第 {index} 项不能为空字符串")
            normalized.append(text)

        return normalized

class DeferredVoteModelItem(BaseModel):
    """表示模型输出的单条 deferred_vote 中间结果。"""

    model_config = ConfigDict(extra="forbid")

    highpoint_id: int = Field(ge=1)
    payload: DeferredVoteModelPayload


class DeferredVoteModelDocument(BaseModel):
    """表示模型输出的 deferred_vote 根文档结构。"""

    model_config = ConfigDict(extra="forbid")

    interactions: list[DeferredVoteModelItem]

    @field_validator("interactions")
    @classmethod
    def validate_interactions(
        cls, value: list[DeferredVoteModelItem]
    ) -> list[DeferredVoteModelItem]:
        """校验同一 highpoint 最多只出现一次。"""
        highpoint_ids: set[int] = set()
        for item in value:
            if item.highpoint_id in highpoint_ids:
                raise ValueError(
                    f"highpoint_id={item.highpoint_id} 重复出现，同一 highpoint 最多只能生成 1 条 deferred_vote"
                )
            highpoint_ids.add(item.highpoint_id)

        return value


class SideCommentModelPayload(BaseModel):
    """表示模型输出的 side_comment payload。"""

    model_config = ConfigDict(extra="forbid")

    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """校验 side_comment 文案非空。"""
        text = value.strip()
        if not text:
            raise ValueError("payload.text 不能为空字符串")
        return text


class SideCommentModelItem(BaseModel):
    """表示模型输出的单条 side_comment 中间结果。"""

    model_config = ConfigDict(extra="forbid")

    highpoint_id: int = Field(ge=1)
    payload: SideCommentModelPayload


class SideCommentModelDocument(BaseModel):
    """表示模型输出的 side_comment 根文档结构。"""

    model_config = ConfigDict(extra="forbid")

    interactions: list[SideCommentModelItem]

    @field_validator("interactions")
    @classmethod
    def validate_interactions(
        cls, value: list[SideCommentModelItem]
    ) -> list[SideCommentModelItem]:
        """校验同一 highpoint 最多只出现一次。"""
        highpoint_ids: set[int] = set()
        for item in value:
            if item.highpoint_id in highpoint_ids:
                raise ValueError(
                    f"highpoint_id={item.highpoint_id} 重复出现，同一 highpoint 最多只能生成 1 条 side_comment"
                )
            highpoint_ids.add(item.highpoint_id)

        return value


class EmotionButtonPayload(BaseModel):
    """表示最终 emotion_button payload。"""

    model_config = ConfigDict(extra="forbid")

    button_id: EmotionButtonId
    text: str | None = None
    danmaku: list[str] | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        """校验最终按钮文案非空、总字符数和禁用词。"""
        if value is None:
            return value

        return validate_emotion_button_copy_text(
            value,
            field_name="payload.text",
            min_chars=EMOTION_BUTTON_TEXT_MIN_CHARS,
            max_chars=EMOTION_BUTTON_TEXT_MAX_CHARS,
        )

    @field_validator("danmaku")
    @classmethod
    def validate_danmaku(cls, value: list[str] | None) -> list[str] | None:
        """校验最终预设弹幕条数、元素非空、总字符数和禁用词。"""
        if value is None:
            return value

        if not value:
            raise ValueError("payload.danmaku 不能为空数组")
        if not (
            EMOTION_BUTTON_DANMAKU_MIN_ITEMS
            <= len(value)
            <= EMOTION_BUTTON_DANMAKU_MAX_ITEMS
        ):
            raise ValueError(
                "payload.danmaku 条数需为 "
                f"{EMOTION_BUTTON_DANMAKU_MIN_ITEMS} 到 {EMOTION_BUTTON_DANMAKU_MAX_ITEMS} 条，"
                f"当前为 {len(value)} 条"
            )

        normalized: list[str] = []
        for index, item in enumerate(value, start=1):
            normalized.append(
                validate_emotion_button_copy_text(
                    item,
                    field_name=f"payload.danmaku 第 {index} 项",
                    min_chars=EMOTION_BUTTON_DANMAKU_MIN_CHARS,
                    max_chars=EMOTION_BUTTON_DANMAKU_MAX_CHARS,
                )
            )

        return normalized

    @model_validator(mode="after")
    def validate_field_combo(self) -> "EmotionButtonPayload":
        """按 button_id 校验 payload 字段组合。"""
        type_name = EMOTION_BUTTON_ID_TO_TYPE[self.button_id]
        rules = EMOTION_BUTTON_FIELD_RULES[type_name]
        has_text = self.text is not None
        has_danmaku = self.danmaku is not None

        if rules["text"] and not has_text:
            raise ValueError(f"button_id={self.button_id} 时 payload.text 必填")
        if not rules["text"] and has_text:
            raise ValueError(f"button_id={self.button_id} 时 payload.text 不允许出现")
        if rules["danmaku"] and not has_danmaku:
            raise ValueError(f"button_id={self.button_id} 时 payload.danmaku 必填")
        if not rules["danmaku"] and has_danmaku:
            raise ValueError(f"button_id={self.button_id} 时 payload.danmaku 不允许出现")

        return self


class RepeatKeylinePayload(BaseModel):
    """表示最终 repeat_keyline payload。"""

    model_config = ConfigDict(extra="forbid")

    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """校验最终复述台词非空。"""
        text = value.strip()
        if not text:
            raise ValueError("payload.text 不能为空字符串")
        return text


class InstantVotePayload(BaseModel):
    """表示最终 instant_vote payload。"""

    model_config = ConfigDict(extra="forbid")

    question: str
    options: list[str]

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        """校验最终投票问题非空。"""
        text = value.strip()
        if not text:
            raise ValueError("payload.question 不能为空字符串")
        return text

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        """校验最终投票选项为 2 个非空字符串。"""
        if len(value) != 2:
            raise ValueError(f"payload.options 必须恰好包含 2 个元素，当前为 {len(value)} 个")

        normalized: list[str] = []
        for index, item in enumerate(value, start=1):
            text = item.strip()
            if not text:
                raise ValueError(f"payload.options 第 {index} 项不能为空字符串")
            normalized.append(text)

        return normalized


class DeferredVotePayload(BaseModel):
    """表示最终 deferred_vote payload。"""

    model_config = ConfigDict(extra="forbid")

    question: str
    options: list[str]
    reveal_time: int = Field(ge=0)
    reveal_delay: int = Field(gt=0)
    answer_id: int = Field(ge=0)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        """校验最终延迟投票问题非空。"""
        text = value.strip()
        if not text:
            raise ValueError("payload.question 不能为空字符串")
        return text

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        """校验最终延迟投票选项为 2 到 4 个非空字符串。"""
        if not 2 <= len(value) <= 4:
            raise ValueError(
                f"payload.options 必须是 2 到 4 个元素的字符串数组，当前为 {len(value)} 个"
            )

        normalized: list[str] = []
        for index, item in enumerate(value, start=1):
            text = item.strip()
            if not text:
                raise ValueError(f"payload.options 第 {index} 项不能为空字符串")
            normalized.append(text)

        return normalized

    @model_validator(mode="after")
    def validate_answer_id(self) -> "DeferredVotePayload":
        """校验最终 answer_id 落在 options 合法范围内。"""
        if self.answer_id >= len(self.options):
            raise ValueError(
                f"payload.answer_id={self.answer_id} 超出 options 范围，当前 options 共有 {len(self.options)} 项"
            )
        return self


class SideCommentPayload(BaseModel):
    """表示最终 side_comment payload。"""

    model_config = ConfigDict(extra="forbid")

    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """校验最终 side_comment 文案非空。"""
        text = value.strip()
        if not text:
            raise ValueError("payload.text 不能为空字符串")
        return text


class EmotionButtonPreparedInteractionItem(BaseModel):
    """表示程序后处理后的 emotion_button interaction。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal[1] = EMOTION_BUTTON_TOP_LEVEL_TYPE
    show_at: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    payload: EmotionButtonPayload


class RepeatKeylinePreparedInteractionItem(BaseModel):
    """表示程序后处理后的 repeat_keyline interaction。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal[2] = REPEAT_KEYLINE_TOP_LEVEL_TYPE
    show_at: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    payload: RepeatKeylinePayload


class InstantVotePreparedInteractionItem(BaseModel):
    """表示程序后处理后的 instant_vote interaction。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal[3] = INSTANT_VOTE_TOP_LEVEL_TYPE
    show_at: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    payload: InstantVotePayload


class DeferredVotePreparedInteractionItem(BaseModel):
    """表示程序后处理后的 deferred_vote interaction。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal[4] = DEFERRED_VOTE_TOP_LEVEL_TYPE
    show_at: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    payload: DeferredVotePayload


class SideCommentPreparedInteractionItem(BaseModel):
    """表示程序后处理后的 side_comment interaction。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal[5] = SIDE_COMMENT_TOP_LEVEL_TYPE
    show_at: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    payload: SideCommentPayload


PreparedInteractionVariant = (
    EmotionButtonPreparedInteractionItem
    | RepeatKeylinePreparedInteractionItem
    | InstantVotePreparedInteractionItem
    | DeferredVotePreparedInteractionItem
    | SideCommentPreparedInteractionItem
)


PreparedInteractionItem = Annotated[
    PreparedInteractionVariant,
    Field(discriminator="type"),
]


class EmotionButtonInteractionItem(BaseModel):
    """表示最终单条 emotion_button 互动标注数据。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    type: Literal[1] = EMOTION_BUTTON_TOP_LEVEL_TYPE
    show_at: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    payload: EmotionButtonPayload


class RepeatKeylineInteractionItem(BaseModel):
    """表示最终单条 repeat_keyline 互动标注数据。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    type: Literal[2] = REPEAT_KEYLINE_TOP_LEVEL_TYPE
    show_at: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    payload: RepeatKeylinePayload


class InstantVoteInteractionItem(BaseModel):
    """表示最终单条 instant_vote 互动标注数据。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    type: Literal[3] = INSTANT_VOTE_TOP_LEVEL_TYPE
    show_at: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    payload: InstantVotePayload


class DeferredVoteInteractionItem(BaseModel):
    """表示最终单条 deferred_vote 互动标注数据。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    type: Literal[4] = DEFERRED_VOTE_TOP_LEVEL_TYPE
    show_at: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    payload: DeferredVotePayload


class SideCommentInteractionItem(BaseModel):
    """表示最终单条 side_comment 互动标注数据。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    type: Literal[5] = SIDE_COMMENT_TOP_LEVEL_TYPE
    show_at: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    payload: SideCommentPayload


InteractionItemVariant = (
    EmotionButtonInteractionItem
    | RepeatKeylineInteractionItem
    | InstantVoteInteractionItem
    | DeferredVoteInteractionItem
    | SideCommentInteractionItem
)


InteractionItem = Annotated[
    InteractionItemVariant,
    Field(discriminator="type"),
]


class DramaInfo(BaseModel):
    """表示单部短剧的参考信息。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    characters: list[str]


class InteractionsDocument(RootModel[list[InteractionItem]]):
    """表示以数组为根节点的最终互动标注列表。"""

    @field_validator("root")
    @classmethod
    def validate_root(cls, value: list[InteractionItem]) -> list[InteractionItem]:
        """校验最终 interaction id 从 1 开始连续递增。"""
        for index, interaction in enumerate(value, start=1):
            if interaction.id != index:
                raise ValueError(
                    f"第 {index} 条 interaction id 应为 {index}，实际为 {interaction.id}"
                )

        return value
