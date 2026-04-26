# Conversion Engine — operations runbook

## Single-worker constraint

The dashboard keeps `_workspace` in memory. Run **exactly one** Uvicorn worker:

```bash
export WEB_CONCURRENCY=1
uvicorn agent.main:app --host 0.0.0.0 --port 8000 --workers 1
```

If `WEB_CONCURRENCY != 1`, the process fails fast at startup.

## Kill switch / outbound

- `KILL_SWITCH=true` (default for demos): no live Resend or Africa’s Talking sends. Clients return `suppressed` payloads.
- `LIVE_OUTREACH=true` **only in development** allows real sends while `KILL_SWITCH` stays true.
- Verify: grep logs for `outbound_suppressed` and confirm no provider HTTP calls when suppressed (use mitmproxy in staging).

## Postgres workspace mirror

Canonical JSON mirrors live in `prospect_workspaces`. After a restart, the API merges mirrors into `_workspace` and re-validates `raw_brief` / `raw_gap`.

- If `GET /api/stats` shows `workspace_persisted: false`, re-run **Enrich** for affected companies.
- Back up `prospect_workspaces` before major upgrades.

## Webhooks

- **Resend**: `RESEND_WEBHOOK_SECRET` is **required** in `production`.
- **Cal.com**: `CALCOM_WEBHOOK_SECRET` must match the secret in Cal; unsigned bodies are rejected.
- Set `WEBHOOK_PUBLIC_BASE` to your HTTPS URL (e.g. ngrok) and register `/webhooks/email`, `/webhooks/cal`, `/webhooks/sms`.

## Incidents

### Resend bounce storm

1. Enable `KILL_SWITCH=true`.
2. Pause sequences (stop process or disable scheduler).
3. Inspect Resend dashboard → suppress bad lists; fix `RESEND_FROM_EMAIL` domain auth.

### Africa’s Talking 502 / rate limits

1. Toggle `KILL_SWITCH`; confirm SMS client returns suppressed.
2. Retry with backoff; check AT status page and sandbox credits.

### Cal.com 4xx / no slots

1. Verify `CALCOM_EVENT_TYPE_ID` and host calendar availability.
2. Check API logs for `CalError` after non-2xx (retries via tenacity).

### Langfuse outage

1. App continues; tracing no-ops or logs warnings.
2. `LANGFUSE_*` keys must still parse at boot — use placeholder keys only in dev.

### Postgres unreachable

1. Enrichment and mirror writes fail; API may still start with warnings.
2. Restore DB connectivity before relying on workspace recovery.

### Playwright / job posts crash

1. Pipeline catches module errors per signal; check logs for `job_posts`.
2. Ensure `JOB_POSTS_SNAPSHOT_DIR` exists or disable job stage in code for degraded mode.

## Data-handling acknowledgement

On first deploy, review `tenacious_sales_data/policy/acknowledgement.md` and create the marker file configured in `DATA_HANDLING_ACK_FILE` (default `.data_handling_acknowledged` in repo root).
