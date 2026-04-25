# Target Failure Mode Analysis

## Target: Offshore Jargon Leak ("Bench" Usage)
**Probe ID:** ADV-BNC-03
**Category:** Tone & Brand Safety
**Description:** The agent fails to suppress internal Tenacious jargon (the word "bench") in public-facing outreach. This triggers a "cheap offshore vendor" perception in senior engineering leaders, a Tier-1 brand violation per `seed/style_guide.md`.

## Business Cost Derivation

### 1. The Variables
- **Baseline Outreach Volume**: 60 touches/week/SDR $\times$ 52 weeks = 3,120 touches/year.
- **Trigger Rate**: 30% (Measured from `probes/probe_library.md`).
- **Signal-Grounded Reply Rate**: 10% (Mid-point of top-quartile 7-12% from `seed/baseline_numbers.md`).
- **Jargon-Impacted Reply Rate**: 2% (Industry baseline floor from `seed/baseline_numbers.md`).
- **ACV Floor**: $180,000 (Conservative estimate for 3-engineer engagement per `seed/baseline_numbers.md` floor logic).
- **Funnel Conversion**: 40% (Disc-to-Prop) $\times$ 25% (Prop-to-Close) = 10% total lead-to-deal conversion.

### 2. The Arithmetic (per 1,000 touches)
*   **Ideal Case (no failure)**: $1,000 \times 10\% \text{ reply rate} \times 10\% \text{ lead-to-deal} = 10 \text{ deals}$.
*   **Failure-Mode Case**:
    *   70% unaffected touches: $700 \times 10\% \times 10\% = 7 \text{ deals}$.
    *   30% jargoned touches: $300 \times 2\% \text{ reply rate} \times 10\% = 0.6 \text{ deals}$.
    *   **Total Actual**: $7.6 \text{ deals}$.
*   **Opportunity Loss**: $10 - 7.6 = 2.4 \text{ deals}$.
*   **Total Annualized Cost**: $2.4 \times \$180,000 = \$432,000 \text{ per 1,000 touches}$.

## ROI Rationale & Comparative Targets

We compared this against two alternative failure modes to determine where remediation resources should be focused.

### Alternative 1: ICP Misclassification (Seed Stage)
- **Cost Pattern**: Wasted top-of-funnel spend.
- **Math**: 15% misclassification rate $\times$ 1,000 touches $\times$ \$50 CPL = \$7,500 wastage.
- **Comparison**: While wasteful, it does not contaminate the remaining 85% of the funnel like a brand-perception failure does.

### Alternative 2: Stalled Scheduling (Time-Zone Math Failure)
- **Cost Pattern**: Yield loss at the scheduling gate.
- **Math**: 15% scheduling failure rate. Assuming these are "replied" leads (100 per 1,000), losing 15 of them at the gate $\times$ 10% close rate = 1.5 lost deals (\$270,000).
- **Comparison**: High impact, but the jargon leak is more prevalent (30% vs 15%) and causes deeper damage to the "Research Partner" brand status.

**Selection Rationale**: The **Offshore Jargon Leak** wins on ROI for remediation because it is both a highly frequent failure (30%) and serves as a "trust killer" that negates the 5x multiplier benefit of using signal-grounded research (dropping conversion from 10% back to industry baseline 2%).
