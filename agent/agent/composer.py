import json
import logging
import re
from typing import Any, Dict, Optional

from agent.agent.insights import CompetitorGapBrief
from agent.agent.outreach_context import build_outreach_prompt_variables, render_grounded_fallback_email
from agent.agent.prompt_loader import prompt_loader
from agent.enrichment import HiringSignalBrief
from agent.integrations.llm_client import llm_client

logger = logging.getLogger(__name__)

# If the model echoes internal research labels, treat as bad output and use cold.md-shaped fallback.
_INTERNAL_DUMP_MARKERS = (
    "Crunchbase ODM",
    "Layoffs.fyi snapshot",
    "Peer sample",
    "Practice gaps",
    "60d hiring velocity",
    "AI maturity score:",
    "Prospect percentile",
    "Sparse sector:",
    "Sample titles:",
    "Peer-side research",
    "for your angle, not to paste",
    "One grounded observation",
    "segment-specific scaling",
    "internal rubric",
)


def _looks_like_internal_brief_dump(body: str) -> bool:
    if not body:
        return True
    hits = sum(1 for m in _INTERNAL_DUMP_MARKERS if m in body)
    if hits >= 2:
        return True
    if "Team,\n\nWe reviewed public signals" in body and "benchmark vs peers" in body:
        return True
    low = body.lower()
    if "one grounded observation" in low and "one question" in low:
        return True
    if "not to paste" in low or "peer-side research" in low:
        return True
    return False


class EmailComposer:
    """
    Signal-grounded outbound email generation (Tenacious Week 10 brief + seed materials).
    """

    async def compose_personalized(
        self,
        hiring_brief: HiringSignalBrief,
        gap_brief: CompetitorGapBrief,
        *,
        salutation_name: str = "",
        scheduling_url: str = "",
    ) -> tuple[Dict[str, str], Dict[str, Any]]:
        """
        Returns (email dict with subject/body, outreach metadata for HubSpot / UI).
        """
        variables = build_outreach_prompt_variables(
            hiring_brief,
            gap_brief,
            salutation_name=salutation_name,
            scheduling_url=scheduling_url or None,
        )
        meta = variables.pop("metadata", {})
        subj_seed = str(variables.get("suggested_subject_line") or "")
        email = await self._generate_from_variables(variables)
        email = self._normalize_professional_output(
            email=email,
            company=str(variables.get("company") or ""),
            scheduling_instruction=str(variables.get("scheduling_instruction") or ""),
            suggested_subject=subj_seed,
        )
        if _looks_like_internal_brief_dump(email["body"]):
            logger.warning("Compose output looked like internal brief dump; using cold-sequence fallback.")
            pack = dict(variables)
            email = render_grounded_fallback_email(pack, scheduling_url=scheduling_url or "")
            email = self._normalize_professional_output(
                email=email,
                company=str(variables.get("company") or ""),
                scheduling_instruction=str(variables.get("scheduling_instruction") or ""),
                suggested_subject=subj_seed,
            )

        tone = await self.validate_tone(email["body"])
        if tone.get("score", 0) < 0.7:
            logger.warning("Tone score low (%s); regenerating once.", tone.get("score"))
            email = await self._generate_from_variables(variables)
            email = self._normalize_professional_output(
                email=email,
                company=str(variables.get("company") or ""),
                scheduling_instruction=str(variables.get("scheduling_instruction") or ""),
                suggested_subject=subj_seed,
            )
            tone2 = await self.validate_tone(email["body"])
            if tone2.get("score", 0) < 0.7 or _looks_like_internal_brief_dump(email["body"]):
                logger.warning("Tone still low after regen (%s); using grounded template.", tone2.get("score"))
                pack = dict(variables)
                email = render_grounded_fallback_email(pack, scheduling_url=scheduling_url or "")
                email = self._normalize_professional_output(
                    email=email,
                    company=str(variables.get("company") or ""),
                    scheduling_instruction=str(variables.get("scheduling_instruction") or ""),
                    suggested_subject=subj_seed,
                )

        return email, meta

    async def compose(
        self,
        lead_name: str,
        company: str,
        hiring_signal_brief: str,
    ) -> Dict[str, str]:
        """
        Legacy entry: one blob of context. Prefer compose_personalized for production.
        """
        prompt = (
            "Compose a short B2B email. Lead: {lead_name} at {company}.\n\nContext:\n{hiring_signal_brief}\n\n"
            "Subject: ... then body. Under 120 words."
        ).format(
            lead_name=lead_name,
            company=company,
            hiring_signal_brief=hiring_signal_brief,
        )
        raw_text = await llm_client.call(prompt=prompt, model_type="dev", json_mode=False)
        lines = raw_text.split("\n")
        subject = lines[0].replace("Subject:", "").strip()
        body = "\n".join(lines[1:]).strip()
        return {"subject": subject, "body": body}

    async def _generate_from_variables(self, variables: Dict[str, Any]) -> Dict[str, str]:
        prompt = prompt_loader.load_prompt("compose_email", variables)
        raw_text = await llm_client.call(
            prompt=prompt,
            model_type="dev",
            json_mode=False,
        )
        lines = raw_text.strip().split("\n")
        subject = lines[0].replace("Subject:", "").strip()
        body = "\n".join(lines[1:]).strip()

        if not subject or not body:
            raise ValueError("LLM failed to provide both Subject and Body in required format.")

        return {"subject": subject, "body": body}

    @staticmethod
    def _normalize_professional_output(
        email: Dict[str, str],
        company: str,
        scheduling_instruction: str,
        *,
        suggested_subject: str = "",
    ) -> Dict[str, str]:
        """
        Final hygiene pass: keep tone direct/professional and prevent awkward over-personalization.
        """
        subject = (email.get("subject") or "").strip()
        body = (email.get("body") or "").strip()

        # Strip noisy marketing phrasing that violates style guide.
        banned = (
            "hope this finds you well",
            "just circling back",
            "just following up",
            "world-class",
            "rockstar",
            "ninja",
            "top talent",
        )
        for phrase in banned:
            body = re.sub(re.escape(phrase), "", body, flags=re.IGNORECASE)

        # Avoid over-casual opener if model drifted.
        body = re.sub(r"^\s*(hey there|hi there)[,!\s]*", "Hello,", body, flags=re.IGNORECASE)
        body = re.sub(r"[ \t]+\n", "\n", body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()

        allowed = ("Request:", "Context:", "Note:", "Question:", "Congrats:", "Follow-up:")
        seed = (suggested_subject or "").strip()[:60]
        fallback_subj = seed or f"Request: 15m on capacity — {company}"[:60]
        if not subject.strip():
            subject = fallback_subj
        elif not subject.startswith(allowed):
            subject = fallback_subj
        elif seed:
            hook = subject.split(":", 1)[-1].strip().lower() if ":" in subject else subject.lower()
            generic_hooks = {
                "",
                "quick question",
                "quick intro",
                "checking in",
                "following up",
                "intro",
                "hello",
                "touching base",
            }
            if hook in generic_hooks or len(hook) < 6:
                subject = seed
        subject = subject[:60]

        # Keep body concise and professional.
        words = body.split()
        if len(words) > 125:
            body = " ".join(words[:125]).rstrip() + "..."

        # If calendar URL is not configured, ensure body does not leak fake placeholders.
        if "Do not include a placeholder or fake calendar URL." in scheduling_instruction:
            body = body.replace("[Add your Cal.com link after enrich]", "")
            body = body.replace("https://cal.com/demo/30min", "two time windows next week")
            body = re.sub(r"https?://cal\.com/[^\s)]+", "", body).strip()
            body = re.sub(r"\n{3,}", "\n\n", body)

        return {"subject": subject, "body": body}

    async def validate_tone(self, email_text: str) -> Dict[str, Any]:
        """
        Scores the tone of the email body via LLM.
        """
        prompt = prompt_loader.load_prompt(
            "tone_score",
            {"message": email_text}
        )

        try:
            result = await llm_client.call(
                prompt=prompt,
                model_type="dev",
                json_mode=True
            )
            if isinstance(result, dict):
                return result
            return json.loads(result)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("Tone validation parse failed: %s", e)
            return {"score": 0.0, "analysis": "tone validation failed"}

# Singleton instance
email_composer = EmailComposer()
