import logging
import time
from contextlib import contextmanager

from langfuse import Langfuse

from agent.config import settings

logger = logging.getLogger(__name__)

langfuse = Langfuse(
    public_key=settings.LANGFUSE_PUBLIC_KEY,
    secret_key=settings.LANGFUSE_SECRET_KEY,
    host=settings.LANGFUSE_BASE_URL,
)


class TraceHandle(str):
    """String subclass for trace id with observation attachment."""

    def __new__(cls, trace_id, observation):
        instance = super().__new__(cls, trace_id)
        instance.observation = observation
        instance.output = None
        instance.token_counts = None
        instance.cost = None
        return instance


@contextmanager
def trace_llm_call(name, input_data, model, metadata=None):
    metadata = metadata or {}
    start_time = time.time()
    observation = langfuse.start_observation(
        as_type="generation",
        name=name,
        input=input_data,
        model=model,
        metadata=metadata,
    )
    trace_id = observation.trace_id
    handle = TraceHandle(trace_id, observation)
    try:
        yield handle
    finally:
        usage = handle.token_counts or {}
        if handle.cost:
            usage["cost"] = handle.cost
        observation.update(output=handle.output, usage=usage)
        observation.end()
        langfuse.flush()


def get_trace_url(trace_id: str) -> str:
    return langfuse.get_trace_url(trace_id=trace_id)


class _NoOpSpan:
    def end(self, output=None, level=None, **kwargs):
        pass


class _NoOpTrace:
    def span(self, name=None, **kwargs):
        return _NoOpSpan()

    def update(self, **kwargs):
        pass


class _ObservationRoot:
    """Langfuse SDK v3+ root span wrapper."""

    def __init__(self, observation):
        self._obs = observation

    def span(self, name=None, **kwargs):
        child = langfuse.start_observation(as_type="span", name=name or "span", **kwargs)
        return _ObservationChild(child)

    def update(self, **kwargs):
        try:
            sm = kwargs.pop("status_message", None)
            if sm is not None:
                md = dict(kwargs.pop("metadata", None) or {})
                md["status_message"] = sm
                kwargs["metadata"] = md
            self._obs.update(**kwargs)
        except Exception as e:
            logger.debug("Langfuse observation update: %s", e)


class _ObservationChild:
    def __init__(self, observation):
        self._obs = observation

    def end(self, output=None, level=None, **kwargs):
        try:
            self._obs.update(output=output, level=level, **kwargs)
            self._obs.end()
        except Exception as e:
            logger.debug("Langfuse span end: %s", e)


def start_root_trace(name: str, **kwargs):
    lf = langfuse
    if hasattr(lf, "trace"):
        try:
            return lf.trace(name=name, **kwargs)
        except Exception as e:
            logger.debug("langfuse.trace failed, falling back: %s", e)
    try:
        obs = lf.start_observation(as_type="span", name=name, **kwargs)
        return _ObservationRoot(obs)
    except Exception as e:
        logger.warning("Langfuse tracing unavailable: %s", e)
        return _NoOpTrace()
