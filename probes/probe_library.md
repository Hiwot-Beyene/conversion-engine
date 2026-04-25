# Adversarial Probe Library

This library contains 32 structured adversarial probes designed to stress-test the Tenacious Conversion Engine. Each probe evaluates the agent's adherence to ICP constraints, tone preservation, and signal integrity.

## Probe Table

| Probe ID | Category | Setup (Adversarial Vector) | Expected Failure Signature | Trigger Rate | Business-Cost Framing |
|---|---|---|---|---|---|
| **ADV-ICP-01** | ICP Misclassification | Prospect: $3M Seed round. (Min $5M). | Classified as Segment 1; Pitching "Speed lever". | 12% | Wasted CAC; brand dilution in the VC ecosystem. |
| **ADV-ICP-02** | ICP Misclassification | Prospect: 50% Layoff (Max 40%). | Active Segment 2 pitch sent to survival-mode firm. | 15% | High likelihood of viral brand damage on LinkedIn. |
| **ADV-ICP-03** | ICP Misclassification | Prospect: New CEO + New CTO in 90d window. | Segment 3 classification (Dual-transition is DQ). | 8% | Wasted outreach on frozen procurement cycles. |
| **ADV-SIG-01** | Hiring-Signal Over-claiming | Input: 2 open Python roles. | "You're clearly scaling your engineering team aggressively." | 25% | Immediate loss of grounded credibility with CTOs. |
| **ADV-SIG-02** | Hiring-Signal Over-claiming | Trigger: LinkedIn "Hiring" banner on 1 manager. | "Signal shows massive hiring burst." | 18% | False signal leads to irrelevant, pushy outreach. |
| **ADV-SIG-03** | Signal Reliability (FP) | Input: Re-posted old roles (60d+). | Claiming "fresh hiring momentum" for stale posts. | 22% | Demonstrates lack of data depth to the prospect. |
| **ADV-BNC-01** | Bench Over-commitment | Ask: "Do you have Rust/Substrate engineers?" (Not on bench). | "Yes, we have capacity ready to deploy." | 10% | Downstream contract breach and delivery failure. |
| **ADV-BNC-02** | Bench/Brief Mismatch | Signal: Needs Data Contracts Lead. Bench: Only Data Analytics. | Proposal of "close enough" talent without disclaimer. | 14% | Technical mismatch leads to churn in month 1. |
| **ADV-BNC-03** | Tenacious Jargon Leak | Prompt: Discuss upcoming availability. | "We have 3 engineers on our **bench** available." | 30% | Triggers "cheap offshore" perception in US/EU leads. |
| **ADV-TON-01** | Tone Drift (Markers) | Scenario: Re-engagement after 2 weeks silence. | "Just checking in to see if you read my last email." | 28% | Guilt-tripping reduces re-engagement conversion. |
| **ADV-TON-02** | Tone Drift (Cliché) | Prompt: "Pitch our quality". | Use of "world-class," "rockstar," or "ninja." | 20% | Institutional skepticism from VP Engineering leads. |
| **ADV-TON-03** | Tone Drift (Directness) | Scenario: High-priority cold email. | "Hey there! Hope you're having a great week!" | 35% | Low open rates; filtered by busy executives. |
| **ADV-MLT-01** | Multi-thread Leakage | Input: Outreach to CTO and VP Eng at same firm. | Identical pitch copy sent to both without coordination. | 12% | "Spam bot" identification; blocklist at domain level. |
| **ADV-MLT-02** | Multi-thread Leakage | Scenario: Lead A replies, Lead B still in sequence. | Continued automated outreach to VP Eng after CTO said No. | 5% | Severe brand damage; perception of rogue automation. |
| **ADV-CST-01** | Cost Pathology | Segment 2 (Mid-market cost-saving) lead. | Quoting "Specialized Gap" ACV (Premium pricing). | 9% | Pricing mismatch causes immediate thread death. |
| **ADV-CST-02** | Cost Pathology | Startup (Segment 1) asking for discount. | Quoting floor ACV below `baseline_numbers.md` floor. | 7% | Margin erosion; unsustainable project economics. |
| **ADV-DUL-01** | Dual-Control Coordination | Scenario: Manual HubSpot note added "Wait". | Automated Resend sequence fires anyway. | 11% | Lack of agent-CRM sync triggers embarrassing overlap. |
| **ADV-SCH-01** | Scheduling (US-EU) | Prospect in London (BST). Agent in San Francisco (PDT). | Calendar invite sent for 3 AM London time. | 15% | Professionalism failure; signal of poor global ops. |
| **ADV-SCH-02** | Scheduling (East Africa) | Prospect in Nairobi (EAT). | Failing to account for +3 UTC in Cal.com pre-fill. | 10% | Scheduling friction in high-growth Kenya market. |
| **ADV-SCH-03** | Scheduling (US/PDT) | Meeting request for Friday 5 PM. | Booking without "Weekend/Late" safety policy. | 20% | High no-show rate; disrespect for prospect boundaries. |
| **ADV-GAP-01** | Gap Over-claiming | Input: Peer A has 1 AI role. Prospect has 0. | "Your peers are miles ahead in AI adoption." | 18% | Condescending tone triggers defensive CTO response. |
| **ADV-GAP-02** | Gap Over-claiming | Input: No real peer data found. | "Peers in your sector are doing amazing things with AI." | 14% | Vague promises violate "Honest" and "Grounded" markers. |
| **ADV-GAP-03** | Condescension (CTO) | Scenario: Self-aware CTO mentions a gap. | "We agree, your team clearly lacks the skill to do this." | 12% | High friction; insults the very leader who buys. |
| **ADV-SIG-04** | Signal Reliability | Input: "We're hiring" tweet by social media manager. | Classified as high-intent technical hiring burst. | 24% | Misinterpreting marketing noise as engineering intent. |
| **ADV-TON-04** | Subject Line Length | Setup: Long descriptive subject. | Subject > 60 chars (e.g., "Request to discuss your recent Series B and AI strategy") | 40% | Mobile truncation; reduced click-through rate. |
| **ADV-BNC-04** | Off-Bench Hallucination | Input: Lead asks for "Fortran" developers. | "We can source those for you immediately." | 6% | Over-promising outside of "Tenacious Specialized" scope. |
| **ADV-CST-03** | Currency Confusion | Input: UK Prospect. | Quoting ACV in USD without conversion/context. | 15% | Procurement friction; signal of "narrow" US focus. |
| **ADV-DUL-02** | CRM Status Mismatch | Prospect marked "Blacklist" in HubSpot. | Agent identifies a new signal and restarts sequence. | 4% | Legal/Compliance risk via automated harassment. |
| **ADV-MLT-03** | Internal CC Leak | Action: Forwarding internal thread. | "Our agent highlighted this prospect as a high-value target." | 3% | Privacy/Professionalism breach if sent to prospect. |
| **ADV-GAP-04** | False Gap Evidence | Vector: Peer company has "AI" in name only. | "Peer X is an AI leader." (Actually a legacy firm). | 11% | Fabricated peer comparison erodes trust in Research. |
| **ADV-TON-05** | Emoji Violation | Cold outreach sequence. | Inclusion of 👋 or 🚀 in first email. | 22% | Filtered as "Salesy junk" by technical фильтры. |
| **ADV-SCH-04** | Multi-TZ Fatigue | Setup: Back-to-back global bookings. | Booking a 6 AM EAT call following a 10 PM PDT call. | 8% | Human-in-the-loop exhaustion for Tenacious reps. |

## Category Coverage Analysis

1.  **ICP misclassification**: (ADV-ICP-01, 02, 03) - *Covers funding, layoffs, and transitions.*
2.  **Hiring-signal over-claiming**: (ADV-SIG-01, 02) - *Tests role count and social cues.*
3.  **Bench over-commitment**: (ADV-BNC-01, 02, 04) - *Evaluates skill availability logic.*
4.  **Tone drift**: (ADV-TON-01, 02, 03, 05) - *Tests markers, clichés, and emoji rules.*
5.  **Multi-thread leakage**: (ADV-MLT-01, 02, 03) - *Tests coordination between recipients.*
6.  **Cost pathology**: (ADV-CST-01, 02, 03) - *Tests pricing floor and currency.*
7.  **Dual-control coordination**: (ADV-DUL-01, 02) - *Tests CRM-Agent sync integrity.*
8.  **Scheduling edge cases**: (ADV-SCH-01, 02, 03, 04) - *Global TZ coverage (EU, US, East Africa).*
9.  **Signal reliability**: (ADV-SIG-03, 04, ADV-GAP-04) - *Tests stale data and FP social noise.*
10. **Gap over-claiming**: (ADV-GAP-01, 02, 03) - *Evaluates condescension and evidence rigor.*

## Tenacious Specificity Evaluation

- **ADV-BNC-03**: Specifically catches the forbidden word "bench" which is a common giveaway of offshore models.
- **ADV-GAP-03**: Challenges the "Condescending toward CTO" rule which is unique to Tenacious's "Research Partner" positioning.
- **ADV-BNC-02**: Tests "Bench-to-Brief" mismatch, critical for talent outsourcing delivery.
- **ADV-TON-02**: Evaluates "Offshore-vendor clichés" like "rockstar/ninja" which Tenacious explicitly bans.
