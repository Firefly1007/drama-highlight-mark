"""按需取证的无状态桩接口。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    QuerySpan,
    validate_derived_observations,
)
from drama_interaction.schemas.interaction import InteractionType


class EvidenceAuditRecord(BaseModel):
    """一次有效 inspect_span 请求的审计信息。"""

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
        if value is not None and not value.strip():
            raise ValueError("审计文本不能仅包含空白字符")
        return value


class InspectSpanResult(BaseModel):
    """按需取证结果；当前桩不会虚构派生观察。"""

    model_config = ConfigDict(extra="forbid")

    observations: list[DerivedObservation] = Field(default_factory=list)
    available: bool
    failure_reason: str | None = None
    audit_record: EvidenceAuditRecord | None = None

    @field_validator("failure_reason")
    @classmethod
    def validate_failure_reason(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("failure_reason 不能仅包含空白字符")
        return value


class EvidenceService:
    """只读基线文档上的按需取证服务。"""

    def __init__(self, document: EvidenceDocument) -> None:
        self._document = document

    def inspect_span(
        self,
        start_ms: int,
        end_ms: int,
        query: str,
        specialist: str,
        existing_derived: tuple[DerivedObservation, ...] | list[DerivedObservation] = (),
    ) -> InspectSpanResult:
        """校验请求并返回明确的不可用结果，不修改任何证据。"""
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

        return self._result(
            specialist_type,
            query_span,
            query,
            failure_reason="按需取证尚未接入媒体提取器",
        )

    @staticmethod
    def _input_error(message: str) -> InspectSpanResult:
        return InspectSpanResult(
            available=False,
            failure_reason=f"输入错误: {message}",
        )

    @staticmethod
    def _result(
        specialist: InteractionType,
        query_span: QuerySpan,
        query: str,
        failure_reason: str,
    ) -> InspectSpanResult:
        audit_record = EvidenceAuditRecord(
            specialist=specialist,
            query_span=query_span,
            query=query,
            result_count=0,
            available=False,
            failure_reason=failure_reason,
        )
        return InspectSpanResult(
            available=False,
            failure_reason=failure_reason,
            audit_record=audit_record,
        )
