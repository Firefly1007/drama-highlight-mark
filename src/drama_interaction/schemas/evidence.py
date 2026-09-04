"""共享证据的数据模型与结构校验。"""

from __future__ import annotations

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
        if not value.strip():
            raise ValueError("query 不能仅包含空白字符")
        return value


class DerivedObservation(_ObservationContent):
    """仅对发起 Specialist 可见的派生客观观察。"""

    id: DerivedObservationId
    refines: ObservationId | DerivedObservationId | None = None
    provenance: EvidenceProvenance


class EvidenceDocument(BaseModel):
    """一集共享基线证据的根对象。"""

    model_config = ConfigDict(extra="forbid")

    episode_duration_ms: StrictInt = Field(gt=0)
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_entries(self) -> EvidenceDocument:
        self._validate_sequence("transcript_segments", self.transcript_segments)
        self._validate_sequence("observations", self.observations)
        return self

    def _validate_sequence(
        self,
        name: str,
        entries: list[TranscriptSegment] | list[Observation],
    ) -> None:
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


def validate_derived_observations(
    document: EvidenceDocument,
    specialist: InteractionType | str,
    observations: list[DerivedObservation],
) -> None:
    """校验一个 Specialist 分支的派生观察引用与集长边界。"""
    specialist_value = InteractionType(specialist).value
    baseline_ids = {observation.id for observation in document.observations}
    derived_ids: set[str] = set()

    for observation in observations:
        if observation.provenance.specialist.value != specialist_value:
            raise ValueError("派生观察必须属于当前 Specialist")
        if (
            observation.end_ms > document.episode_duration_ms
            or observation.provenance.query_span.end_ms > document.episode_duration_ms
        ):
            raise ValueError("派生观察及其 query_span 不能超过 episode_duration_ms")
        if observation.id in derived_ids:
            raise ValueError("同一 Specialist 的派生观察 id 必须唯一")
        if observation.refines is not None:
            if observation.refines.startswith("O"):
                if observation.refines not in baseline_ids:
                    raise ValueError("refines 必须引用存在的基线 Observation")
            elif observation.refines not in derived_ids:
                raise ValueError("refines 只能引用当前 Specialist 中先前的 DerivedObservation")
        derived_ids.add(observation.id)
