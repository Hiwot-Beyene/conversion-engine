import logging
import json
from typing import Dict, Any
from agent.agent.prompt_loader import prompt_loader
from agent.integrations.llm_client import llm_client

logger = logging.getLogger(__name__)

class ReplyQualifier:
    """
    Classifies lead replies to determine the next best action in the orchestrator.
    """

    async def qualify(self, user_reply: str) -> Dict[str, Any]:
        """
        Loads the qualification prompt and uses the LLM to categorize the user's intent.
        """
        logger.info(f"Qualifying lead reply: {user_reply[:50]}...")

        # 1. Load and format prompt
        try:
            prompt = prompt_loader.load_prompt(
                "qualify_reply", 
                {"user_reply": user_reply}
            )
        except Exception as e:
            logger.error(f"Failed to load qualification prompt: {e}")
            return {"intent": "error", "confidence": 0}

        # 2. Call LLM
        try:
            response = await llm_client.call(
                prompt=prompt,
                model_type="dev", 
                json_mode=True
            )
            
            # 3. Mandatory Safety Parsing
            try:
                # If json_mode=True, llm_client might already return a dict
                if isinstance(response, dict):
                    return response
                return json.loads(response)
            except:
                return {"intent": "unclear", "confidence": 0}

        except Exception as e:
            logger.error(f"Error during reply qualification: {e}")
            return {"intent": "unclear", "confidence": 0}

# Singleton instance
reply_qualifier = ReplyQualifier()
