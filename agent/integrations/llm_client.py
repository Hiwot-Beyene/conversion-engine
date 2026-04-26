import logging
import json
import asyncio
from typing import Optional, Dict, Any, Union
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agent.config import settings
from agent.integrations.langfuse_client import trace_llm_call

logger = logging.getLogger(__name__)

class LLMError(Exception):
    """Base exception for LLM client errors."""
    pass

class LLMClient:
    """
    Production-grade OpenRouter client with integrated retries, 
    structured output support, and model selection.
    """

    def __init__(self):
        key = settings.llm.openrouter_api_key
        self.api_key = (
            key.get_secret_value()
            if key is not None and hasattr(key, "get_secret_value")
            else (str(key) if key else None)
        )
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://conversion-engine.ai", # Required by OpenRouter
            "X-Title": "Conversion Engine Agent",
            "Content-Type": "application/json"
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, LLMError)),
        reraise=True
    )
    async def call(
        self,
        prompt: str,
        variables: Optional[Dict[str, Any]] = None,
        model_type: str = "dev",  # "dev" or "eval"
        json_mode: bool = False,
        temperature: float = 0.1
    ) -> Union[str, Dict[str, Any]]:
        """
        Executes a call to the LLM via OpenRouter.
        """
        if not self.api_key:
            raise LLMError("OpenRouter API key is not configured.")

        # 1. Format Prompt
        formatted_prompt = prompt
        if variables:
            try:
                formatted_prompt = prompt.format(**variables)
            except KeyError as e:
                logger.error(f"Missing variable in prompt formatting: {e}")
                raise LLMError(f"Prompt formatting error: {e}")

        # 2. Select Model
        model = settings.llm.default_model if model_type == "dev" else settings.llm.eval_model
        
        # 3. Handle JSON Mode
        messages = [{"role": "user", "content": formatted_prompt}]
        if json_mode:
            messages.insert(0, {"role": "system", "content": "You are a helpful assistant that ALWAYS returns valid JSON."})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if json_mode:
            # Some models support response_format, for others we rely on the prompt
            payload["response_format"] = {"type": "json_object"}

        trace_in = {"prompt_preview": formatted_prompt[:2000], "json_mode": json_mode}

        try:
            with trace_llm_call(
                name="openrouter_chat",
                input_data=trace_in,
                model=model,
                metadata={"temperature": temperature, "model_type": model_type},
            ) as trace_handle:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        self.base_url,
                        headers=self.headers,
                        json=payload,
                    )

                if response.status_code == 429:
                    logger.warning("OpenRouter rate limit hit. Retrying...")
                    raise LLMError("Rate limit exceeded")

                if response.status_code != 200:
                    logger.error(f"OpenRouter error: {response.status_code} - {response.text}")
                    raise LLMError(f"API Error: {response.text}")

                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage") or {}
                trace_handle.token_counts = {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                }

                if json_mode:
                    try:
                        out = json.loads(content)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON from LLM: {content}")
                        cleaned = content.replace("```json", "").replace("```", "").strip()
                        try:
                            out = json.loads(cleaned)
                        except json.JSONDecodeError:
                            raise LLMError("LLM failed to return valid JSON.")
                    trace_handle.output = out
                    return out

                trace_handle.output = content[:4000]
                return content

        except httpx.RequestError as e:
            logger.error(f"Network error calling OpenRouter: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in LLM call: {e}")
            raise LLMError(str(e))

# Singleton instance
llm_client = LLMClient()
