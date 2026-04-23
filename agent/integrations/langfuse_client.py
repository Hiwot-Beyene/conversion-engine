import os
import time
from contextlib import contextmanager
from langfuse import Langfuse
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
# Renamed to LANGFUSE_BASE_URL to match your .env file
LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL", os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"))

# Initialize the Langfuse client
langfuse = Langfuse(
    public_key=LANGFUSE_PUBLIC_KEY,
    secret_key=LANGFUSE_SECRET_KEY,
    host=LANGFUSE_BASE_URL
)

class TraceHandle(str):
    """
    A string subclass that allows attaching metadata for Langfuse.
    This satisfies the requirement of returning a trace_id as a string 
    while allowing the context manager to record data on exit.
    """
    def __new__(cls, trace_id, observation):
        instance = super().__new__(cls, trace_id)
        instance.observation = observation # This is the observation object from Langfuse SDK v3/v4
        instance.output = None
        instance.token_counts = None # Should be a dict like {"prompt_tokens": 0, "completion_tokens": 0}
        instance.cost = None
        return instance

@contextmanager
def trace_llm_call(name, input_data, model, metadata={}):
    """
    A context manager to trace LLM calls.
    Returns a TraceHandle (which behaves like a trace_id string).
    Supports Langfuse SDK v3/v4 (OpenTelemetry native).
    """
    start_time = time.time()
    
    # In Langfuse SDK v3+, we use start_observation with as_type="generation"
    observation = langfuse.start_observation(
        as_type="generation",
        name=name,
        input=input_data,
        model=model,
        metadata=metadata
    )
    
    # Getting the trace_id from the observation object
    trace_id = observation.trace_id
    
    handle = TraceHandle(trace_id, observation)
    
    try:
        yield handle
    finally:
        # Record output, token counts, cost estimate, and latency on exit
        usage = handle.token_counts or {}
        if handle.cost:
            usage["cost"] = handle.cost
            
        # Record output and usage using update() before ending the observation
        # In modern Langfuse SDK, end() does not accept these as keyword arguments
        observation.update(
            output=handle.output,
            usage=usage
        )
        observation.end()
        # Force flush to ensure it's sent immediately
        langfuse.flush()

def get_trace_url(trace_id: str) -> str:
    """
    Returns the Langfuse cloud URL for a given trace_id.
    """
    return langfuse.get_trace_url(trace_id=trace_id)
