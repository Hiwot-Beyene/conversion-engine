from agent.enrichment import EnrichmentSignal
from agent.enrichment.tech_stack import enrich_from_tech_stack


def test_tech_stack_inference_from_roles():
    jp = EnrichmentSignal(
        source="job_posts_scraper",
        confidence=0.8,
        data={
            "roles": [
                "Senior Python Backend Engineer",
                "MLOps Engineer",
                "React Frontend Engineer",
            ]
        },
    )
    out = enrich_from_tech_stack(jp)
    assert out.source == "tech_stack_inference"
    assert "python" in (out.data.get("languages") or [])
    assert out.data.get("has_mlops_signal") is True
    assert out.confidence > 0


def test_tech_stack_inference_handles_missing_signal():
    out = enrich_from_tech_stack(None)
    assert out.source == "tech_stack_inference"
    assert out.error is None
    assert "note" in out.data
