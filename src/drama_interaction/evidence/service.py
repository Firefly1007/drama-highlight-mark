"""V2 Specialist 按需视频取证服务。"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from drama_interaction.config import INSPECTION_MAX_SPAN_MS, Settings
from drama_interaction.evidence.extract import run_qwen_video_observer
from drama_interaction.media import slice_video
from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    EvidenceProvenance,
    QuerySpan,
    validate_derived_observations,
)
from drama_interaction.schemas.interaction import InteractionType


class EvidenceAuditRecord(BaseModel):
    """一次有效 ``inspect_span`` 请求的审计信息。

    Attributes:
        specialist: 发起查询的 Specialist。
        query_span: 查询时间范围。
        query: 查询问题。
        result_count: 返回的派生观察数量。
        available: 是否成功取得证据。
        failure_reason: 不可用时的原因。
    """

    model_config = ConfigDict(extra="forbid")

    specialist: InteractionType
    query_span: QuerySpan
    query: str = Field(min_length=1)
    result_count: StrictInt = Field(ge=0)
    available: bool
    failure_reason: str | None = None

    @field_validator("query", "failure_reason")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        """拒绝空白审计文本。

        Args:
            value: 待校验文本。

        Returns:
            原始文本。

        Raises:
            ValueError: 当文本仅包含空白字符时抛出。
        """
        if value is not None and not value.strip():
            raise ValueError("审计文本不能仅包含空白字符")
        return value


class InspectSpanResult(BaseModel):
    """一次按需视频取证结果。

    Attributes:
        observations: 取证得到的派生观察。
        available: 是否成功取得证据。
        failure_reason: 不可用时的原因。
        audit_record: 有效请求的审计记录。
    """

    model_config = ConfigDict(extra="forbid")

    observations: list[DerivedObservation] = Field(default_factory=list)
    available: bool
    failure_reason: str | None = None
    audit_record: EvidenceAuditRecord | None = None

    @field_validator("failure_reason")
    @classmethod
    def validate_failure_reason(cls, value: str | None) -> str | None:
        """拒绝空白失败原因。

        Args:
            value: 待校验失败原因。

        Returns:
            原始失败原因。

        Raises:
            ValueError: 当失败原因仅包含空白字符时抛出。
        """
        if value is not None and not value.strip():
            raise ValueError("failure_reason 不能仅包含空白字符")
        return value


class EvidenceService:
    """只读基线文档上的按需取证服务。

    Args:
        document: 共享基线证据文档。
    """

    def __init__(
        self,
        document: EvidenceDocument,
        video_path: str | None = None,
        run_dir: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        """保存只读的共享基线证据。

        Args:
            document: 共享基线证据文档。
        """
        self._document = document
        self._video_path = video_path
        self._run_dir = run_dir
        self._settings = settings
        self._inspection_lock = Lock()
        self.audit_records: list[EvidenceAuditRecord] = []
        self.derived_observations: list[DerivedObservation] = []

    def inspect_span(
        self,
        start_ms: int,
        end_ms: int,
        query: str,
        specialist: str,
        existing_derived: tuple[DerivedObservation, ...] | list[DerivedObservation] = (),
    ) -> InspectSpanResult:
        """校验请求并返回明确的不可用结果，不修改任何证据。

        Args:
            start_ms: 查询开始时间。
            end_ms: 查询结束时间。
            query: 取证问题。
            specialist: 发起查询的 Specialist。
            existing_derived: 当前 Specialist 已有的派生观察。

        Returns:
            按需取证结果及有效请求的审计记录。
        """
        with self._inspection_lock:
            return self._inspect_span(
                start_ms,
                end_ms,
                query,
                specialist,
                existing_derived,
            )

    def _inspect_span(
        self,
        start_ms: int,
        end_ms: int,
        query: str,
        specialist: str,
        existing_derived: tuple[DerivedObservation, ...]
        | list[DerivedObservation] = (),
    ) -> InspectSpanResult:
        if type(start_ms) is not int or type(end_ms) is not int:
            return self._input_error("start_ms 和 end_ms 必须为整数")
        if not isinstance(query, str) or not query.strip():
            return self._input_error("query 必须为非空白字符串")
        try:
            specialist_type = InteractionType(specialist)
        except (TypeError, ValueError):
            return self._input_error("specialist 必须是五类互动之一")
        if start_ms < 0 or end_ms < start_ms or end_ms > self._document.episode_duration_ms:
            return self._input_error("query_span 必须位于本集范围内且 start_ms 不晚于 end_ms")

        query_span = QuerySpan(start_ms=start_ms, end_ms=end_ms)
        try:
            validate_derived_observations(
                self._document, specialist_type, list(existing_derived)
            )
        except ValueError as exc:
            return self._result(
                specialist_type,
                query_span,
                query,
                failure_reason=f"existing_derived 非法: {exc}",
            )
        if end_ms - start_ms > (
            self._settings.inspection_max_span_ms
            if self._settings
            else INSPECTION_MAX_SPAN_MS
        ):
            return self._result(
                specialist_type, query_span, query,
                failure_reason="query_span 超过 INSPECTION_MAX_SPAN_MS",
            )

        if not self._video_path or not self._settings or not self._run_dir:
            return self._result(specialist_type, query_span, query, failure_reason="视频观察不可用")
        try:
            clip = slice_video(
                self._video_path, start_ms, end_ms,
                str(
                    Path(self._run_dir)
                    / "inspection"
                    / f"{specialist_type.value}-{len(self.audit_records) + 1}.mp4"
                ),
            )
            values = run_qwen_video_observer(clip, query, self._settings)
        except Exception:
            return self._result(specialist_type, query_span, query, failure_reason="视频观察不可用")
        facts = sum((values.get(field, []) for field in ("visual_observations", "onscreen_texts", "audio_observations", "uncertainty")), [])
        observations: list[DerivedObservation] = []
        if facts:
            observations.append(DerivedObservation(
                id=f"D{len(existing_derived) + len(self.derived_observations) + 1}", start_ms=start_ms, end_ms=end_ms,
                visual_observations=values.get("visual_observations", []),
                onscreen_texts=values.get("onscreen_texts", []),
                audio_observations=values.get("audio_observations", []),
                uncertainty=values.get("uncertainty", []),
                provenance=EvidenceProvenance(specialist=specialist_type, query_span=query_span, query=query),
            ))
            self.derived_observations.extend(observations)
        return self._result(specialist_type, query_span, query, observations=observations, available=True)

    @staticmethod
    def _input_error(message: str) -> InspectSpanResult:
        """构造不记录审计的输入错误结果。

        Args:
            message: 输入错误说明。

        Returns:
            不可用的取证结果。
        """
        return InspectSpanResult(
            available=False,
            failure_reason=f"输入错误: {message}",
        )

    def _result(
        self,
        specialist: InteractionType,
        query_span: QuerySpan,
        query: str,
        failure_reason: str | None = None,
        observations: list[DerivedObservation] | None = None,
        available: bool = False,
    ) -> InspectSpanResult:
        """构造带审计记录的取证结果。

        Args:
            specialist: 发起查询的 Specialist。
            query_span: 查询时间范围。
            query: 取证问题。
            failure_reason: 结果不可用的原因。

        Returns:
            不可用的取证结果。
        """
        audit_record = EvidenceAuditRecord(
            specialist=specialist,
            query_span=query_span,
            query=query,
            result_count=0,
            available=False,
            failure_reason=failure_reason,
        )
        audit_record.available = available
        audit_record.result_count = len(observations or [])
        self.audit_records.append(audit_record)
        return InspectSpanResult(available=available, observations=observations or [], failure_reason=failure_reason, audit_record=audit_record)
