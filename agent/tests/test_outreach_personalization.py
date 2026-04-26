from agent.agent.outreach_context import render_grounded_fallback_email


def test_fallback_abstain_uses_second_digest_paragraph_when_present():
    digest = (
        "Public hiring visibility is low for Barakatalan after checking 4 public source page(s).\n\n"
        "Current sector tag in our data is Advertising; we can tailor examples only if that still reflects your setup."
    )
    out = render_grounded_fallback_email(
        {
            "company": "Barakatalan",
            "segment_key": "abstain",
            "email_digest": digest,
            "job_count": 0,
            "ai_maturity_integer": 1,
            "suggested_subject_line": "Context: Advertising + hiring — Barakatalan",
        }
    )
    body = out["body"]
    assert "Current sector tag in our data is Advertising" in body
    assert "Public data is thin on our side" not in body
    assert "Tuesday or Wednesday next week work for a 15-minute call about Barakatalan" in body
