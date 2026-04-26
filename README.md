# 🚀 Tenacious Conversion Engine

The **Tenacious Conversion Engine** is a production-grade multi-channel sales automation system. It manages the first 72 hours of the lead lifecycle—from signal enrichment (Crunchbase/Job Posts) through SMS/Email qualification to automated CRM (HubSpot) and Calendar (Cal.com) orchestration.

## 🏗️ Architecture & Data Flow (Criterion 1)

```mermaid
graph TD
    subgraph SignalLayer [Signal Discovery]
        CB[Crunchbase ODM] --> EP[Enrichment Pipeline]
        JP[Job Posts / Layoffs] --> EP
    end

    subgraph Core [Backbone & Orchestration]
        EP -->|Merged Brief| LLM[LLM Agent: Sonnet 3.5 / Qwen]
        LLM -->|Decision Logic| GCN[Global Coordinate-Normalizer]
        GCN -->|Channel Dispatch| CH[Channel Handlers]
    end

    subgraph Channels [Execution & Multi-Channel]
        CH -->|SMS| AT[Africa's Talking]
        CH -->|Email| RS[Resend]
        CH -->|Booking| CAL[Cal.com]
    end

    subgraph Persistance [Persistence & Observability]
        CH -->|Write| HS[HubSpot CRM]
        LLM -->|Trace| LF[Langfuse / Trace Log]
        AT -->|Webhook| HS
    end
```

## 📂 Directory Index (Criterion 3)

| Path | Purpose |
| :--- | :--- |
| `agent/` | **Core Backend**: FastAPI server, tool orchestration, and multi-channel policies. |
| `frontend/` | **Management Dashboard**: High-fidelity React UI for SDR lead management. |
| `data/` | **Static Signal Snapshots**: Ground-truth CSVs for layoffs, jobs, and firmographics. |
| `probes/` | **Adversarial Library**: Structured tests (P-001 - P-030) for edge-case validation. |
| `eval/` | **Benchmarking**: Evaluation results (`score_log.json`) and trace trajectories. |
| `docs/` | **Knowledge Base**: Project requirements, scenario docs, and baseline references. |
| `tenacious_sales_data/` | **Domain Seed**: ICP definitions, bench counts, and pricing sheets. |
| `memo/` | **Executive Delivery**: Final decision memo and evidence-graph artifacts. |
| `scratch/` | **Workbench**: Diagnostic scripts, database inspection tools, and one-off tests. |

## 🛠️ Setup & Bootstrapping (Criterion 2)

### Prerequisites
- **Python 3.10+** (System or `uv` venv)
- **Node.js 18+** (for Frontend)
- **Docker** (PostgreSQL + Redis/Persistence)
- **Africa's Talking Sandbox** (for SMS)

### Pinning Dependencies
Ensure you install specific versions to avoid runtime drift:
```bash
# Python
pip install fastapi==0.109.0 uvicorn==0.27.0 pydantic==2.5.3 sqlalchemy==2.0.25
# Node
npm install (vite 5.0+, react 18.2+)
```

### Configuration Variables (.env)
| Variable | Explanation | Value Example |
| :--- | :--- | :--- |
| `OPENROUTER_API_KEY` | Backbone LLM access. | `sk-or-v1-...` |
| `AT_API_KEY` | Africa's Talking Sandbox Key. | `...-at-key` |
| `AT_USERNAME` | Must be `sandbox`. | `sandbox` |
| `DATABASE_URL` | Local persistence. | `postgresql://ce_user:pass@localhost/conversion_engine` |
| `HUB_API_KEY` | HubSpot CRM Integration. | `pat-na1-...` |

### Explicit Run Order
1. **Initialize Infra**: `docker-compose up -d`
2. **Setup Environment**: `source .venv/bin/activate && pip install -r agent/requirements.txt`
3. **Database Migration**: `python3 -m agent.db.init`
4. **Boot Backend** (single worker — required for in-memory `_workspace`):
   ```bash
   export WEB_CONCURRENCY=1
   uvicorn agent.main:app --host 0.0.0.0 --port 8000 --workers 1
   ```
5. **Boot Frontend**: `cd frontend && npm install && npm run dev`  
   Set `VITE_DEMO_EMAIL` and `VITE_HUBSPOT_PORTAL_ID` in `frontend/.env`.

### Reliability & recovery

- **Kill switch**: `KILL_SWITCH=true` blocks real Resend / Africa’s Talking I/O (clients return `suppressed`). See `docs/RUNBOOK.md`.
- **Postgres mirror**: Dashboard state is mirrored to `prospect_workspaces`. After a restart, the API merges JSON back and re-validates briefs. If `GET /api/stats` returns `workspace_persisted: false`, re-run **Enrich** for that company.
- **Webhooks**: In `production`, `RESEND_WEBHOOK_SECRET` and `CALCOM_WEBHOOK_SECRET` are required at startup.
- **Eval harness**: `make eval` runs `eval/tau2/runner.py` (API should be listening). `make smoke` runs a quick import + pytest subset.

## 🐘 Known Limitations & Handoff (Criterion 4)

### Known Limitations
- **Sandbox Lag**: Africa's Talking Sandbox can occasionally delay webhooks by 45s+; production API bypasses this via private routing.
- **Resend DMARC**: Cold emails are currently gated to verified domains to prevent SPAM flagging.
- **Context Window**: Long multi-day SMS threads (50+ turns) can occasionally incur token bloat.

### Successor Next Steps
- [ ] **GCN Optimization**: Fully implement the *Global Coordinate-Normalizer* to reduce EAT/PST scheduling friction.
- [ ] **Voice Rig Integration**: Implement the Voice bonus channel for inbound qualification calls.
- [ ] **A/B Testing Harness**: Partition leads to compare `Strict-Safety` vs `Aggressive-Closure` agent personas.
