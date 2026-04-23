import logging
from typing import Dict, Any, List
from agent.agent.prompt_loader import prompt_loader
from agent.integrations.llm_client import llm_client

logger = logging.getLogger(__name__)

class InsightGenerator:
    """
    Generates strategic business insights from enriched data.
    """

    async def generate_competitor_gap(self, signals: Dict[str, Any], competitors: List[str]) -> str:
        """
        Calculates the competitive gap between a lead's company and their rivals.
        """
        logger.info("Generating competitor gap insight...")

        # 1. Load and format prompt
        try:
            prompt = prompt_loader.load_prompt(
                "competitor_gap", 
                {
                    "signals": str(signals),
                    "competitors": ", ".join(competitors)
                }
            )
        except Exception as e:
            logger.error(f"Failed to load insight prompt: {e}")
            return ""

        # 2. Call LLM
        try:
            insight = await llm_client.call(
                prompt=prompt,
                model_type="dev", 
                json_mode=False
            )
            
            # Simple validation: ensure it's not empty and fairly concise
            if not insight or len(insight) < 10:
                logger.warning("LLM returned empty or too short insight.")
                return "We noticed some interesting shifts in your competitive landscape."

            return insight.strip()

        except Exception as e:
            logger.error(f"Error during insight generation: {e}")
            return "Your current market positioning presents some unique opportunities for growth."

# Singleton instance
insight_generator = InsightGenerator()
