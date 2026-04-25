# Mechanism Design: Semantic Jargon Interceptor (SJI)

## 1. Executive Summary
The **Semantic Jargon Interceptor (SJI)** is an egress filter designed to eliminate "Offshore Jargon Leaks" (ADV-BNC-03). It ensures all outreach adheres to the Tenacious "Research Partner" positioning by intercepting and remediating drafts that contain forbidden terms or offshore-cliché patterns.

## 2. Re-Implementable Specification

The SJI is implemented as an interceptor pattern between the `EmailComposer` and the `OutreachOrchestrator`.

### Data Flow
1. **Input**: A completed email draft string.
2. **Phase 1: Token Blocking (Deterministic)**
   - Maintain a `BANNED_TOKENS` list: `["bench", "ninja", "rockstar", "A-player", "top talent", "hiring ninja"]`.
   - Perform case-insensitive regex search. If any term is found, trigger **REJECT**.
3. **Phase 2: Semantic Grading (Probabilistic)**
   - Call an LLM with the following system prompt:
     > "Score the following email draft on 'Institutional Trustworthiness' (0.0 to 1.0). Deduct points for: offshore clichés, excessive pleasantries, and vague capability claims. A score below 0.85 indicates a failure."
   - If `trust_score < 0.85`, trigger **REMEDIATE**.
4. **Phase 3: Remediation Loop**
   - On **REJECT** or **REMEDIATE**, the draft is sent back to the `EmailComposer` with the specific violation note.
   - Max retries: 2. If failure persists, route to the **Human Review Queue**.

## 3. Design Rationale
**Target Failure Mode**: Offshore Jargon Leak (ADV-BNC-03).
**Root Cause**: Base LLMs are biased toward "generic recruiter" training data. When prompted for talent outcomes, they naturally revert to terms like "bench availability" which triggers institutional skepticism in CTOs. 
**Remediation Strategy**: The SJI addresses this by decoupling the **Creative** act (composing the pitch) from the **Audit** act (enforcing brand standards). It acts as a deterministic boundary that the generative bias cannot cross.

## 4. Hyperparameters

| Parameter | Value | Rationale |
|---|---|---|
| `INTERCEPT_THRESHOLD` | **0.85** | High-precision bar; favors brand safety over agent throughput. |
| `REGEN_MAX_RETRIES` | **2** | Prevents infinite loops while allowing for non-deterministic "fixed" outputs. |
| `SEMANTIC_COSINE_LIMIT` | **0.90** | Threshold for comparing draft embeddings against "Style Guide Gold Standard" examples. |
| `REGEX_SENSITIVITY` | **Case-Insensitive**| Prevents "Bench", "BENCH", or "bench" leaks. |

## 5. Ablation Variants

| Variant | Change | Purpose of Test |
|---|---|---|
| **A: Token-Only** | Remove Phase 2 (LLM Scrutiny). | Quantifies the value of semantic understanding vs. simple blacklists. |
| **B: Vanilla (Baseline)**| Remove SJI entirely. | Baseline to measure brand damage and reply-rate floor. |
| **C: Low-Gate** | Set `INTERCEPT_THRESHOLD` = 0.5. | Tests the impact of "moderate" vs. "strict" brand enforcement on lead conversion. |

## 6. Statistical Test Plan
To validate the SJI, we will perform a **Randomized Controlled Trial** during the conversion-engine pilot.

- **Test**: Unpaired Two-Sample T-Test.
- **Comparison**: Outbound cohort using SJI (Experimental) vs. Outbound cohort using Vanilla Baseline (Control).
- **Primary Metric**: **Reply Rate (%)** – Normalized by touch-volume.
- **Sample Size**: 500 touches per cohort (Powered to detect a 3% absolute difference in reply rate).
- **P-Value Threshold**: $\alpha < 0.05$.
- **Hypothesis ($H_1$)**: The SJI-managed group will exhibit a significantly higher reply rate (> 7%) compared to the control group (< 3%) by preserving the "Research Partner" status and avoiding "Offshore" spam filters.
