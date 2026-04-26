"""Hiring / competitor gap schema builders must emit Draft 2020-12–valid instances."""

from agent.agent.insights import CompetitorGapBrief, PracticeGap
from agent.agent.schema_validate import (
    build_competitor_gap_schema_instance,
    build_hiring_signal_schema_instance,
    validate_competitor_gap,
    validate_hiring_signal,
)
from agent.enrichment import HiringSignalBrief


def test_hiring_brief_coerces_segment_and_clamps_confidence():
    brief = HiringSignalBrief(company_name="Co", signals={}, overall_confidence=0.5, ai_maturity=None)
    inst = build_hiring_signal_schema_instance(
        brief,
        prospect_domain="co.example",
        primary_segment_match="not_a_valid_segment",
        segment_confidence=1.7,
    )
    assert inst["primary_segment_match"] == "abstain"
    assert inst["segment_confidence"] == 1.0
    ok, err = validate_hiring_signal(inst)
    assert ok, err


def test_hiring_brief_omits_null_buying_window_dates():
    from agent.enrichment import EnrichmentSignal, SignalMetadata

    brief = HiringSignalBrief(
        company_name="Co",
        signals={
            "crunchbase": EnrichmentSignal(
                source="crunchbase",
                data={
                    "funding_round": "Series A",
                    "funding_amount_usd": 5_000_000,
                    "funding_date": "not-a-date",
                },
                confidence=0.9,
                metadata=SignalMetadata(),
            ),
        },
        overall_confidence=0.5,
        ai_maturity=None,
    )
    inst = build_hiring_signal_schema_instance(
        brief,
        prospect_domain="co.example",
        primary_segment_match="abstain",
        segment_confidence=0.2,
    )
    fe = inst["buying_window_signals"]["funding_event"]
    assert fe["detected"] is True
    assert "closed_at" not in fe
    ok, err = validate_hiring_signal(inst)
    assert ok, err


def test_competitor_gap_stays_within_peer_bounds():
    gap = CompetitorGapBrief(
        prospect_company="Co",
        sector="SaaS",
        percentile_position=0.5,
        competitors_analyzed=[f"Peer {i}" for i in range(10)],
        prospect_ai_score=0.4,
        competitor_avg_score=0.55,
        gaps=[
            PracticeGap(
                practice_name="MLOps hiring",
                evidence="Peer job posts",
                impact="Contrast",
                source_url="https://example.com/jobs",
            )
        ],
        is_sparse_sector=False,
    )
    brief = HiringSignalBrief(company_name="Co", signals={}, overall_confidence=0.5, ai_maturity=None)
    inst = build_competitor_gap_schema_instance(
        gap, brief, prospect_domain="co.example", primary_segment_match="invalid"
    )
    peers = inst["competitors_analyzed"]
    assert 5 <= len(peers) <= 10
    assert sum(1 for r in peers if "(prospect)" in str(r.get("name") or "")) == 1
    # No fabricated .example peer domains in API payloads.
    for row in peers:
        name = str(row.get("name") or "").lower()
        dom = str(row.get("domain") or "")
        if "sector peer" in name:
            assert not dom.endswith(".example")
    ok, err = validate_competitor_gap(inst)
    assert ok, err
