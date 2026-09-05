"""证据时间线的 gap 与分支隔离测试。"""

from drama_interaction.evidence.render import render_evidence_timeline
from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    EvidenceProvenance,
    Observation,
    TranscriptSegment,
)


def _derived(identifier: str, specialist: str, start_ms: int, end_ms: int) -> DerivedObservation:
    return DerivedObservation(
        id=identifier,
        start_ms=start_ms,
        end_ms=end_ms,
        visual_observations=[f"{identifier} 观察"],
        provenance=EvidenceProvenance(
            specialist=specialist,
            query_span={"start_ms": start_ms, "end_ms": end_ms},
            query="补充观察",
        ),
    )


def test_render_keeps_all_reportable_gaps():
    document = EvidenceDocument(
        episode_duration_ms=20_000,
        transcript_segments=[
            TranscriptSegment(id="T1", start_ms=2_000, end_ms=4_000, text="第一句"),
            TranscriptSegment(id="T2", start_ms=8_000, end_ms=9_000, text="第二句"),
        ],
        observations=[
            Observation(id="O1", start_ms=4_000, end_ms=6_000, visual_observations=["动作"]),
            Observation(id="O2", start_ms=12_000, end_ms=13_000, visual_observations=["反应"]),
        ],
    )

    timeline = render_evidence_timeline(
        document,
        "instant_vote",
        min_reported_gap_ms=1_000,
    )

    assert timeline.count("[未覆盖 ") == 4
    assert "[未覆盖 00:00:00.000–00:00:02.000]" in timeline
    assert "[未覆盖 00:00:06.000–00:00:08.000]" in timeline
    assert "[未覆盖 00:00:09.000–00:00:12.000]" in timeline
    assert "[未覆盖 00:00:13.000–00:00:20.000]" in timeline


def test_render_exposes_only_the_requested_branch():
    document = EvidenceDocument(episode_duration_ms=10_000)
    instant = _derived("D1", "instant_vote", 1_000, 2_000)
    side_comment = _derived("D2", "side_comment", 3_000, 4_000)

    instant_timeline = render_evidence_timeline(document, "instant_vote", [instant])
    side_timeline = render_evidence_timeline(document, "side_comment", [side_comment])

    assert "[D1] 00:00:01.000–00:00:02.000" in instant_timeline
    assert "[D2] 00:00:03.000–00:00:04.000" not in instant_timeline
    assert "[D2] 00:00:03.000–00:00:04.000" in side_timeline
    assert "[D1] 00:00:01.000–00:00:02.000" not in side_timeline
