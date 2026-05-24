import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

_PUNCT_RE = re.compile(r"[，。！？、；：""''（）【】《》…—,.!?;:\"'(){}<>-]")


def _normalize_text(text: str) -> str:
    """轻度归一化：去空白、去标点、全角转半角。"""
    text = re.sub(r"\s+", "", text)
    text = _PUNCT_RE.sub("", text)
    text = unicodedata.normalize("NFKC", text)
    return text


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


class HighlightEvidence(BaseModel):
    """表示单条高光的证据结构。"""
    model_config = ConfigDict(extra="forbid")

    segment_ids: list[int]
    dialogues: list[str] = Field(default_factory=list)
    signals: list[str]

    @field_validator("segment_ids")
    @classmethod
    def validate_segment_ids(cls, value: list[int]) -> list[int]:
        """校验证据片段 id 非空且升序。"""
        if not value:
            raise ValueError("evidence.segment_ids 不能为空")

        if value != sorted(value):
            raise ValueError("evidence.segment_ids 必须按升序排列")

        return value


class HighlightItem(BaseModel):
    """表示模型输出的单条高光数据（不含 start/end，由程序派生）。"""
    model_config = ConfigDict(extra="forbid")

    id: int
    label: str
    level: Literal[1, 2, 3]
    summary: str
    reason: str
    evidence: HighlightEvidence


class HighlightOutput(BaseModel):
    """表示最终落盘的单条高光数据（含由 segment_ids 派生的 start/end）。"""
    model_config = ConfigDict(extra="forbid")

    id: int
    start: str = Field(pattern=TIMESTAMP_PATTERN)
    end: str = Field(pattern=TIMESTAMP_PATTERN)
    label: str
    level: Literal[1, 2, 3]
    summary: str
    reason: str
    evidence: HighlightEvidence


class HighlightsDocument(BaseModel):
    """表示高光片段列表的根文档结构。"""
    model_config = ConfigDict(extra="forbid")

    highlights: list[HighlightItem]

    @field_validator("highlights")
    @classmethod
    def validate_highlights(cls, value: list[HighlightItem]) -> list[HighlightItem]:
        """校验高光 id 连续递增。"""
        for index, highlight in enumerate(value, start=1):
            if highlight.id != index:
                raise ValueError(
                    f"第 {index} 个高光 id 应为 {index}，实际为 {highlight.id}"
                )

        return value

    def validate_against_segments(self, segments: list) -> list["HighlightOutput"]:
        """交叉校验 highlights 与原始 segments 数据，返回含 start/end 的输出列表。

        校验项：
        - segment_ids 非空、升序、每个 id 存在于原始 segments
        - 每条 dialogue 能在 segment_ids 对应的任意一个 segment.text 中找到
        校验通过后，由 segment_ids 自动派生 start/end。
        """
        segment_map = {seg.id: seg for seg in segments}
        outputs: list[HighlightOutput] = []

        for i, highlight in enumerate(self.highlights, start=1):
            ids = highlight.evidence.segment_ids

            for sid in ids:
                if sid not in segment_map:
                    raise ValueError(
                        f"第 {i} 个高光引用了不存在的 segment {sid}"
                    )

            first_seg = segment_map[ids[0]]
            last_seg = segment_map[ids[-1]]

            evidence_texts = [_normalize_text(segment_map[sid].text) for sid in ids]
            for j, dialogue in enumerate(highlight.evidence.dialogues, start=1):
                norm_dialogue = _normalize_text(dialogue)
                if not any(norm_dialogue in text for text in evidence_texts):
                    raise ValueError(
                        f"第 {i} 个高光第 {j} 条 dialogue 未在 "
                        f"segment {ids} 的 text 中找到: {dialogue!r}"
                    )

            outputs.append(HighlightOutput(
                id=highlight.id,
                start=first_seg.start,
                end=last_seg.end,
                label=highlight.label,
                level=highlight.level,
                summary=highlight.summary,
                reason=highlight.reason,
                evidence=highlight.evidence,
            ))

        return outputs


class HighlightsList(RootModel[list[HighlightItem]]):
    """表示以数组为根节点的高光列表。"""

    @field_validator("root")
    @classmethod
    def validate_root(cls, value: list[HighlightItem]) -> list[HighlightItem]:
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
