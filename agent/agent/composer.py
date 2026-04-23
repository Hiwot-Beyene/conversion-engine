import logging
from typing import Dict, Any, Optional
from agent.agent.prompt_loader import prompt_loader
from agent.integrations.llm_client import llm_client

logger = logging.getLogger(__name__)

class EmailComposer:
    """
    Handles the generation of personalized outbound emails using LLMs.
    """

    async def compose(
        self, 
        lead_name: str, 
        company: str, 
        hiring_signal_brief: str
    ) -> Dict[str, str]:
        """
        Generates an email and validates its tone. Regenerates once if validation fails.
        """
        # Attempt 1
        email = await self._generate_email_draft(lead_name, company, hiring_signal_brief)
        
        # Tone Validation
        tone = await self.validate_tone(email["body"])
        
        if tone.get("score", 0) < 0.7:
            logger.warning(f"Tone score too low ({tone['score']}). Regenerating email...")
            # Attempt 2 (Regenerate once)
            email = await self._generate_email_draft(lead_name, company, hiring_signal_brief)
            
        return email

    async def _generate_email_draft(self, lead_name: str, company: str, hiring_signal_brief: str) -> Dict[str, str]:
        """Core generation logic with mandatory text parsing."""
        prompt = prompt_loader.load_prompt(
            "compose_email", 
            {
                "lead_name": lead_name,
                "company": company,
                "hiring_signal_brief": hiring_signal_brief
            }
        )

        raw_text = await llm_client.call(
            prompt=prompt,
            model_type="dev", 
            json_mode=False
        )
        
        # Parse Email (MANDATORY implementation)
        lines = raw_text.split("\n")
        subject = lines[0].replace("Subject:", "").strip()
        body = "\n".join(lines[1:]).strip()

        if not subject or not body:
            raise ValueError("LLM failed to provide both Subject and Body in required format.")

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
            # Mandatory parsing safety (Matches qualifier pattern)
            if isinstance(result, dict):
                return result
            return json.loads(result)
        except:
            return {"score": 0.0, "analysis": "tone validation failed"}

# Singleton instance
email_composer = EmailComposer()
