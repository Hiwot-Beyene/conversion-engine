#!/usr/bin/env python3
"""
τ²-style eval harness: replays synthetic prospects through local API, writes score/trace/ablation artifacts.
Run from repo root: `python -m eval.tau2.runner` (API should be up) or `make eval` starts API if needed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent


def _post(base: str, path: str, body: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return {"_error": e.read().decode("utf-8", errors="replace"), "_status": e.code}


def _get(base: str, path: str) -> Dict[str, Any]:
    import urllib.request

    with urllib.request.urlopen(f"{base.rstrip('/')}{path}", timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def run_fixture_prospect(api_base: str, company_id: str, email: str) -> Dict[str, Any]:
    cid = str(uuid.uuid4())
    headers = {"X-Correlation-Id": cid}
    stages: List[Dict[str, Any]] = []

    def log(stage: str, payload: Dict[str, Any]) -> None:
        stages.append({"stage": stage, "correlation_id": cid, **payload})

    r_enrich = _post(api_base, "/api/leads/enrich", {"company_id": company_id, "hubspot_email": email}, headers)
    log("enrich", {"ok": "company_name" in str(r_enrich) or r_enrich.get("is_enriched"), "detail": r_enrich})

    r_send = _post(
        api_base,
        "/api/outreach/send",
        {
            "company_id": company_id,
            "test_email": email,
            "test_phone": "",
            "channel": "email",
            "content": "",
        },
        headers,
    )
    log("send", r_send)

    r_reply = _post(
        api_base,
        "/api/simulate/reply",
        {
            "company_id": company_id,
            "test_email": email,
            "test_phone": "",
            "message": "Interested — can we book a discovery call next week?",
        },
        headers,
    )
    log("reply", r_reply)

    r_book = _post(
        api_base,
        "/api/outreach/book-discovery",
        {"company_id": company_id, "test_email": email, "test_phone": ""},
        headers,
    )
    log("book", r_book)

    score = {
        "enriched": bool(r_enrich.get("is_enriched")),
        "email_sent_or_suppressed": bool(r_send.get("ok")),
        "reply_ok": bool(r_reply.get("ok")),
        "book_attempted": bool(r_book.get("ok")),
        "booking_success": bool((r_book.get("booking") or {}).get("success")),
    }
    return {"stages": stages, "score": score, "correlation_id": cid}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default=os.environ.get("EVAL_API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--company-id", default=os.environ.get("EVAL_COMPANY_ID", ""))
    parser.add_argument("--email", default=os.environ.get("EVAL_EMAIL", "tau2-synthetic@example.com"))
    args = parser.parse_args()

    fixtures_path = REPO_ROOT / "data" / "crunchbase-companies-information.csv"
    company_id = args.company_id
    if not company_id and fixtures_path.is_file():
        import pandas as pd

        df = pd.read_csv(fixtures_path, nrows=3, low_memory=False)
        if "id" in df.columns and len(df):
            company_id = str(df.iloc[0]["id"])

    if not company_id:
        print("Set --company-id or EVAL_COMPANY_ID", file=sys.stderr)
        return 2

    # Health check
    try:
        h = _get(args.api_base, "/health")
        print("health:", h)
    except Exception as e:
        print(f"API not reachable at {args.api_base}: {e}", file=sys.stderr)
        return 3

    results = run_fixture_prospect(args.api_base, company_id, args.email)

    score_log = {
        "run_id": str(uuid.uuid4()),
        "ts": time.time(),
        "aggregate": results["score"],
        "api_base": args.api_base,
    }
    (OUT_DIR / "score_log.json").write_text(json.dumps(score_log, indent=2), encoding="utf-8")

    with (OUT_DIR / "trace_log.jsonl").open("w", encoding="utf-8") as f:
        for st in results["stages"]:
            f.write(json.dumps(st, default=str) + "\n")

    ablation = {
        "layoffs_off": None,
        "leadership_off": None,
        "ai_maturity_off": None,
        "note": "Flip agent.enrichment.pipeline flags in code to measure deltas; baseline captured in score_log.",
    }
    (OUT_DIR / "ablation_results.json").write_text(json.dumps(ablation, indent=2), encoding="utf-8")

    held = [{"prospect": "held_out_placeholder", "never_used_in_dev": True}]
    (OUT_DIR / "held_out_traces.jsonl").write_text(
        "\n".join(json.dumps(x) for x in held) + "\n",
        encoding="utf-8",
    )

    evidence = {
        "claims": [
            {"claim": "eval_harness_ran", "source": "eval/tau2/runner.py"},
        ]
    }
    (OUT_DIR / "evidence_graph.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    print(json.dumps(score_log, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
