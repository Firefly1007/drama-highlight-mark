"""V2 证据适配与按需取证接口。"""

from drama_interaction.evidence.adapter import (
    adapt_file,
    convert_v1_segments_to_evidence,
    parse_time_str_to_ms,
    save_evidence_document,
)
from drama_interaction.evidence.service import (
    EvidenceAuditRecord,
    EvidenceService,
    InspectSpanResult,
)

__all__ = [
    "EvidenceAuditRecord",
    "EvidenceService",
    "InspectSpanResult",
    "adapt_file",
    "convert_v1_segments_to_evidence",
    "parse_time_str_to_ms",
    "save_evidence_document",
]
