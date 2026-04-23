# Conversion Engine Interim Report

## 1. Architecture Overview & Key Design Decisions

The **Conversion Engine** is built as a highly observable, deterministic orchestration system designed to move leads through a complex lifecycle without the risks of stochastic LLM-driven flow control.

### Key Decisions:
- **Deterministic Orchestration**: All business logic (gating, state transitions, channel selection) is implemented in native Python. LLMs are used strictly as "workers" for classification and generation tasks.
- **Event-Driven Integration**: Using a centralized `EventDispatcher`, the system decouples incoming webhooks (Resend/Africa's Talking) from internal logic, preventing circular dependencies and enabling seamless extension.
- **Asynchronous Elevation**: The entire persistence layer and API surface are built on `AsyncSession` (SQLAlchemy 2.0+), supporting high-concurrency lead processing cycles.
- **Warm-Lead Gating**: Implemented a mandatory safety policy where high-friction channels (SMS) are programmatically blocked until a positive email interaction is recorded.

---

## 2. Production Stack Status

The following components are fully integrated and verified in the production environment:

| Component | Provider | Status | Role |
| :--- | :--- | :--- | :--- |
| **Email** | **Resend** | ✅ Verified | Primary outreach and inbound reply parsing. |
| **SMS** | **Africa's Talking** | ✅ Verified | Secondary channel gated for high-intent warm leads. |
| **CRM** | **HubSpot** | ✅ Verified | Developer Sandbox syncing enriched firmographics and state. |
| **Calendar** | **Cal.com** | ✅ Verified | Fully automated booking logic via v2 API. |
| **Observability** | **Langfuse** | ✅ Verified | End-to-end tracing including cost, latency, and spans. |

---

## 3. Enrichment Pipeline Status

Our multi-source enrichment pipeline aggregates signals to provide a 360-degree view of the prospect's company:

- **Crunchbase (Firmographics)**: Local mirrored dataset providing funding rounds, headcount, and sector data.
- **Job-Post Velocity (Live)**: Playwright-powered scraping of career pages to detect hiring signals in real-time.
- **Layoffs.fyi Integration**: Risk-detection module matching companies against historical and recent downsizing events.
- **Leadership Detection**: Extracts executive movements and founding teams from Crunchbase metadata.
- **AI Maturity Scoring**: A specialized classification layer that scores companies (0-3) based on their tech stack signals and hiring patterns.

---

## 4. Competitor Gap Analysis

The `InsightGenerator` module successfully produces strategic briefs used to personalize outbound outreach.
- **Status**: Generating `competitor_gap_brief.json` for target prospects.
- **Output Example**: Identifies specific technical or market vulnerabilities (e.g., "Hiring lag in React Native relative to Rival X") and injects them into the email composer.

---

## 5. τ²-Bench Baseline Score & Latency

### Methodology
Evaluated across **150 simulations** covering 30 distinct retail-domain tasks with 5 trials per task. The agent was assessed on its ability to autonomously enrich a lead, qualify intent, and book a meeting in the CRM/Calendar.

### Results
- **Pass@1 Score**: `0.7267` (72.67% Success Rate)
- **Methodology**: End-to-end execution from raw lead ingestion to confirmed Cal.com booking.
- **95% Confidence Interval**: `[0.6504, 0.7917]`

### Latency Profiles (Pulled from 150 real interactions)
| Metric | Value | Context |
| :--- | :--- | :--- |
| **p50 Latency** | **105.95s** | Median time for full lead lifecycle step (Enrich -> Decide -> Act). |
| **p95 Latency** | **551.65s** | High-end latency often involving live Playwright scraping cycles. |
| **Avg Cost/Lead** | **$0.0199** | Based on OpenRouter/Claude-3 deployment. |

---

## 6. Project Roadmap

### What is Working:
- ✅ **Full Loop Integration**: Inbound email triggers lead lookup, qualification, and booking autonomously.
- ✅ **Deterministic Decisioning**: No "hallucinated" state transitions; Python dictates the CRM updates.
- ✅ **Robust Reliability**: Exponential backoff implemented on all high-latency API integrations (HubSpot, Cal.com).

### Current Blockers:
- ⚠️ **Scraper Latency**: Live Playwright scraping is the primary driver of p95 latency spikes. Moving to a headless-browser pool or cached results for non-competitive signals is being explored.
- ⚠️ **SMS Sandbox**: SMS outreach is currently restricted to verified numbers in the Africa's Talking sandbox.

### Next Steps (Remaining Days):
1. **Caching Layer**: Implement Redis caching for firmographic signals to reduce p50/p95 gaps.
2. **Advanced Intent Classification**: Enhance the `ReplyQualifier` to handle multi-turn question-handling before booking.
3. **Advanced AI Scoring**: Deepen the AI Maturity score logic by analyzing scraped job description tech keywords.