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


def test_render_derives_covered_empty_and_merges_adjacent_slices():
    document = EvidenceDocument(
        episode_duration_ms=9_000,
        transcript_segments=[
            TranscriptSegment(id="T1", start_ms=1_000, end_ms=2_000, text="第一句"),
            TranscriptSegment(id="T2", start_ms=3_500, end_ms=4_500, text="第二句"),
        ],
        observations=[
            Observation(id="O1", start_ms=0, end_ms=3_000, visual_observations=["动作"]),
        ],
    )

    timeline = render_evidence_timeline(
        document,
        "instant_vote",
    )

    # 3000-6000 and 6000-9000 are empty, merged into 3000-9000
    assert "[已覆盖、无可记录观察 start_ms=3000 end_ms=9000]" in timeline
    assert "[未覆盖" not in timeline
    assert "00:00:" not in timeline
    assert "[T1 start_ms=1000 end_ms=2000] 台词：第一句" in timeline
    assert "[O1 start_ms=0 end_ms=3000] 画面：动作" in timeline


def test_render_exposes_only_the_requested_branch():
    document = EvidenceDocument(episode_duration_ms=10_000)
    instant = _derived("D1", "instant_vote", 1_000, 2_000)
    side_comment = _derived("D2", "side_comment", 3_000, 4_000)

    instant_timeline = render_evidence_timeline(document, "instant_vote", [instant])
    side_timeline = render_evidence_timeline(document, "side_comment", [side_comment])

    assert "[D1 start_ms=1000 end_ms=2000]" in instant_timeline
    assert "[D2" not in instant_timeline
    assert "[D2 start_ms=3000 end_ms=4000]" in side_timeline
    assert "[D1" not in side_timeline
    assert "00:00:" not in instant_timeline
    assert "00:00:" not in side_timeline


def test_render_transcript_and_derived_do_not_eliminate_covered_empty():
    """测试台词 T 与派生证据 D 都不能替代基线 Observation 的覆盖状态。"""
    document = EvidenceDocument(
        episode_duration_ms=6_000,
        transcript_segments=[
            TranscriptSegment(id="T1", start_ms=3_500, end_ms=4_500, text="第二句"),
        ],
        observations=[],
    )
    derived = _derived("D1", "instant_vote", 1_000, 2_000)

    timeline = render_evidence_timeline(document, "instant_vote", [derived])

    # 即使存在 T1 和 D1，由于没有基线 Observation，空切片 0-3000 和 3000-6000 合并为 0-6000
    assert "[已覆盖、无可记录观察 start_ms=0 end_ms=6000]" in timeline
    assert "[T1 start_ms=3500 end_ms=4500]" in timeline
    assert "[D1 start_ms=1000 end_ms=2000]" in timeline

