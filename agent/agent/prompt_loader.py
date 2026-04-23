import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class PromptLoader:
    """
    Utility for loading and formatting dynamic prompts from text files.
    Ensures centralized management of LLM instructions.
    """

    def __init__(self, prompts_dir: Optional[str] = None):
        # Default to agent/agent/prompts
        if prompts_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.prompts_dir = os.path.join(base_dir, "prompts")
        else:
            self.prompts_dir = prompts_dir

    def load_prompt(self, filename: str, variables: Optional[Dict[str, Any]] = None) -> str:
        """
        Loads a prompt from a file and injects variables.
        """
        # Ensure extension
        if not filename.endswith(".txt"):
            filename += ".txt"
            
        file_path = os.path.join(self.prompts_dir, filename)
        
        if not os.path.exists(file_path):
            logger.error(f"Prompt file not found: {file_path}")
            raise FileNotFoundError(f"Prompt file '{filename}' was not found in {self.prompts_dir}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            if variables:
                return content.format(**variables)
            return content
            
        except KeyError as e:
            logger.error(f"Missing variable for prompt '{filename}': {e}")
            raise ValueError(f"Prompt '{filename}' requires variable {e} which was not provided.")
        except Exception as e:
            logger.error(f"Error loading prompt '{filename}': {e}")
            raise

# Singleton instance for easy access
prompt_loader = PromptLoader()
