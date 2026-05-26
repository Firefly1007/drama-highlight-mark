from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

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


class InteractionItem(BaseModel):
    """表示单条互动标注数据。"""

    model_config = ConfigDict(extra="allow")


class DramaInfo(BaseModel):
    """表示单部短剧的参考信息。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    characters: list[str]


class InteractionsDocument(BaseModel):
    """表示互动标注列表的根文档结构。"""

    model_config = ConfigDict(extra="forbid")

    interactions: list[InteractionItem]
