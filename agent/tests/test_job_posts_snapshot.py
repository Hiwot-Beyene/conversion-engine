"""Job posts module: prefer local snapshot over live Playwright when present."""
import json
from pathlib import Path

import pytest

from agent.enrichment import job_posts as jp


def test_is_plausible_public_job_title_filters_marketing_headings():
    assert jp.is_plausible_public_job_title("How Consolety Works") is False
    assert jp.is_plausible_public_job_title("Senior Backend Engineer") is True
    assert jp.is_plausible_public_job_title("Careers") is False


def test_jobish_ambiguous_filter_is_narrow():
    assert jp._looks_jobish_but_ambiguous("Careers in Côte d'Ivoire") is True
    assert jp._looks_jobish_but_ambiguous("Open positions") is True
    assert jp._looks_jobish_but_ambiguous("How Bank of Africa Works") is False
    assert jp._looks_jobish_but_ambiguous("About us") is False


def test_load_job_snapshot_from_tmp_dir(tmp_path, monkeypatch):
    snap_dir = tmp_path / "snap"
    snap_dir.mkdir()
    payload = {"job_count": 3, "urls": ["https://example.com/careers"]}
    (snap_dir / "acme-corp.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(jp.settings, "JOB_POSTS_SNAPSHOT_DIR", str(snap_dir))
    out = jp._load_job_snapshot(None, "Acme Corp")
    assert out is not None
    assert out.get("job_count") == 3
