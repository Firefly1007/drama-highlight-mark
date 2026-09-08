"""共享证据的数据模型与结构校验。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from drama_interaction.schemas.interaction import InteractionType

TranscriptId = Annotated[str, Field(pattern=r"^T[1-9]\d*$")]
ObservationId = Annotated[str, Field(pattern=r"^O[1-9]\d*$")]
DerivedObservationId = Annotated[str, Field(pattern=r"^D[1-9]\d*$")]
EvidenceId: TypeAlias = TranscriptId | ObservationId | DerivedObservationId


class _TimedEvidence(BaseModel):
    """带单集毫秒跨度的证据基类。"""

    model_config = ConfigDict(extra="forbid")

    start_ms: StrictInt = Field(ge=0)
    end_ms: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_span(self) -> _TimedEvidence:
        """校验时间跨度不倒置。

        Returns:
            校验通过的证据对象。

        Raises:
            ValueError: 当开始时间晚于结束时间时抛出。
        """
        if self.start_ms > self.end_ms:
            raise ValueError("start_ms 不能大于 end_ms")
        return self


class TranscriptSegment(_TimedEvidence):
    """一条带精确时间跨度的台词证据。"""

    id: TranscriptId
    text: str = Field(min_length=1)
    speaker_label: str | None = None

    @field_validator("text", "speaker_label")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        """拒绝空白文本。

        Args:
            value: 待校验文本。

        Returns:
            原始文本。

        Raises:
            ValueError: 当文本仅包含空白字符时抛出。
        """
        if value is not None and not value.strip():
            raise ValueError("文本字段不能仅包含空白字符")
        return value


class _ObservationContent(_TimedEvidence):
    """观察证据共享的客观文本字段。"""

    visual_observations: list[str] = Field(default_factory=list)
    onscreen_texts: list[str] = Field(default_factory=list)
    audio_observations: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)

    @field_validator(
        "visual_observations",
        "onscreen_texts",
        "audio_observations",
        "uncertainty",
    )
    @classmethod
    def validate_text_items(cls, values: list[str]) -> list[str]:
        """拒绝仅包含空白字符的观察项。

        Args:
            values: 观察文本列表。

        Returns:
            原始观察文本列表。

        Raises:
            ValueError: 当任一观察项为空白时抛出。
        """
        if any(not value.strip() for value in values):
            raise ValueError("观察文本不能仅包含空白字符")
        return values


class Observation(_ObservationContent):
    """由基线提取器产生的一条客观观察。"""

    id: ObservationId


class QuerySpan(_TimedEvidence):
    """一次按需取证请求的原始时间范围。"""


class EvidenceProvenance(BaseModel):
    """派生观察的 Specialist 与查询来源。"""

    model_config = ConfigDict(extra="forbid")

    specialist: InteractionType
    query_span: QuerySpan
    query: str = Field(min_length=1)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        """拒绝空白查询。

        Args:
            value: 取证查询文本。

        Returns:
            原始查询文本。

        Raises:
            ValueError: 当查询仅包含空白字符时抛出。
        """
        if not value.strip():
            raise ValueError("query 不能仅包含空白字符")
        return value


class DerivedObservation(_ObservationContent):
    """仅对发起 Specialist 可见的派生客观观察。"""

    id: DerivedObservationId
    provenance: EvidenceProvenance


class EvidenceDocument(BaseModel):
    """一集共享基线证据的根对象。"""

    model_config = ConfigDict(extra="forbid")

    episode_duration_ms: StrictInt = Field(gt=0)
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_entries(self) -> EvidenceDocument:
        """校验基线证据的唯一性、顺序和集长边界。

        Returns:
            校验通过的证据文档。

        Raises:
            ValueError: 当证据标识、顺序或时间范围非法时抛出。
        """
        self._validate_sequence("transcript_segments", self.transcript_segments)
        self._validate_sequence("observations", self.observations)
        return self

    def _validate_sequence(
        self,
        name: str,
        entries: list[TranscriptSegment] | list[Observation],
    ) -> None:
        """校验一组基线证据的顺序、标识和时间范围。

        Args:
            name: 证据列表名称，用于错误信息。
            entries: 待校验的证据列表。

        Raises:
            ValueError: 当列表不满足基线证据约束时抛出。
        """
        ids = [entry.id for entry in entries]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{name} 中的 id 必须唯一")
        if any(
            previous.start_ms > current.start_ms
            for previous, current in zip(entries, entries[1:], strict=False)
        ):
            raise ValueError(f"{name} 必须按 start_ms 升序传入")
        if any(entry.end_ms > self.episode_duration_ms for entry in entries):
            raise ValueError(f"{name} 中的时间不能超过 episode_duration_ms")


EvidenceEntry: TypeAlias = TranscriptSegment | Observation | DerivedObservation


def visible_evidence_entries(
    document: EvidenceDocument,
    specialist_type: str,
    derived_observations: Sequence[DerivedObservation],
) -> dict[str, EvidenceEntry]:
    """构造基线证据与当前 Specialist 分支派生证据的可见索引。"""

    entries: dict[str, EvidenceEntry] = {
        entry.id: entry for entry in document.transcript_segments
    }
    entries.update({entry.id: entry for entry in document.observations})
    entries.update(
        {
            entry.id: entry
            for entry in derived_observations
            if entry.provenance.specialist.value == specialist_type
        }
    )
    return entries


def validate_derived_observations(
    document: EvidenceDocument,
    specialist: InteractionType | str,
    observations: list[DerivedObservation],
) -> None:
    """校验一个 Specialist 分支的派生观察引用与集长边界。

    Args:
        document: 共享基线证据文档。
        specialist: 当前派生观察所属的 Specialist。
        observations: 当前 Specialist 产生的派生观察列表。

    Raises:
        ValueError: 当分支、引用或时间范围不符合约束时抛出。
    """
    specialist_value = InteractionType(specialist).value
    derived_ids: set[str] = set()

    for observation in observations:
        # 派生观察只能留在当前 Specialist 分支内。
        if observation.provenance.specialist.value != specialist_value:
            raise ValueError("派生观察必须属于当前 Specialist")
        if (
            observation.end_ms > document.episode_duration_ms
            or observation.provenance.query_span.end_ms > document.episode_duration_ms
        ):
            raise ValueError("派生观察及其 query_span 不能超过 episode_duration_ms")
        if observation.id in derived_ids:
            raise ValueError("同一 Specialist 的派生观察 id 必须唯一")
        derived_ids.add(observation.id)


__all__ = [
    "TranscriptId",
    "ObservationId",
    "DerivedObservationId",
    "EvidenceId",
    "EvidenceEntry",
    "TranscriptSegment",
    "Observation",
    "QuerySpan",
    "EvidenceProvenance",
    "DerivedObservation",
    "EvidenceDocument",
    "visible_evidence_entries",
    "validate_derived_observations",
]
