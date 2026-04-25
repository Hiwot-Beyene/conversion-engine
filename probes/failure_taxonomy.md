# Failure Taxonomy: Adversarial Probes

This taxonomy groups the 32 adversarial probes into 10 distinct failure categories. Each category represents a shared failure pattern observed during stress-testing.

## Taxonomy Overview

| Category | Probes | Aggregate Trigger Rate | Pattern Description |
|---|---|---|---|
| **1. ICP Integrity** | ADV-ICP-01, 02, 03 | 11.7% | Failure to respect hard boundary filters (funding, layoffs, dual-transition) leading to irrelevant outreach. |
| **2. Signal Reliability** | ADV-SIG-01, 02, 03, 04, ADV-GAP-04 | 20.6% | Misinterpretation of weak or stale technical signals (low role count, social noise) as high-intent buying windows. |
| **3. Bench Alignment** | ADV-BNC-01, 02, 04 | 10.0% | Over-committing to niche technical capabilities or volumes not currently validated in `bench_summary.json`. |
| **4. Tone & Brand Safety** | ADV-TON-01, 02, 03, 04, 05, ADV-BNC-03 | 27.7% | Drift from "Direct/Grounded" markers; use of forbidden jargon ("bench"), emojis, or offshore-vendor clichés. |
| **5. Multi-Thread Coordination** | ADV-MLT-01, 02, 03 | 6.7% | Failure to synchronize messaging across multiple stakeholders at a single firm, leading to "spam bot" perception. |
| **6. Pricing & cost Logic** | ADV-CST-01, 02, 03 | 10.3% | Quoting ACVs outside of segment bands or failing to handle currency/pricing floor constraints correctly. |
| **7. SDR-Agent Dual-Control** | ADV-DUL-01, 02 | 7.5% | Misalignment with manual CRM overrides (HubSpot "Wait" or "Blacklist" notes), causing agent rogue behavior. |
| **8. Global Logistics** | ADV-SCH-01, 02, 03, 04 | 13.3% | Time-zone conversion failures and boundary-respect errors for US, EU, and East Africa (Nairobi) prospects. |
| **9. Competitive Gap Rigor** | ADV-GAP-01, 02 | 16.0% | Over-claiming the severity of competitor gaps without sufficient comparative evidence or grounded peer data. |
| **10. Stakeholder Engagement**| ADV-GAP-03 | 12.0% | Failure to avoid condescension when pitching high-level stakeholders (VPE/CTO) about their own technical gaps. |

## Category Patterns

### 1. ICP Integrity
**Pattern:** The agent prioritizes "Segment Match" over "Disqualifying Filter." For example, seeing a $14M round (Segment 1) but ignoring a 50% layoff (DQ).
**Impact:** High brand-risk outreach.

### 4. Tone & Brand Safety
**Pattern:** High frequency of pleasantries ("Hope you're well") and subject-line fluff ("Quick question").
**Impact:** Lowered institutional trust; filtered as low-value automated sales spam.

### 8. Global Logistics
**Pattern:** UTC math errors. The agent fails to anchor to the prospect's local business hours, specifically for EAT (Nairobi) and BST (London) transitions.
**Impact:** Massive friction at the scheduling gate.
