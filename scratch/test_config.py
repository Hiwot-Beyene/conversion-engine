from pydantic import BaseModel, Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class LLMConfig(BaseModel):
    api_key: str = Field(validation_alias=AliasChoices("OPENROUTER_API_KEY", "LLM__API_KEY"))

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")
    llm: LLMConfig

os.environ["OPENROUTER_API_KEY"] = "sk-test-123"

try:
    s = Settings()
    print(f"Success: {s.llm.api_key}")
except Exception as e:
    print(f"Error: {e}")
