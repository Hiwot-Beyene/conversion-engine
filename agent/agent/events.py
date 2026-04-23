import logging
import asyncio
from typing import Callable, Dict, List, Any, Awaitable
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class ConversionEvent(BaseModel):
    """Base class for all system events."""
    event_name: str
    payload: Dict[str, Any]

class EventDispatcher:
    """
    A lightweight, asynchronous event dispatcher for decoupling 
    webhooks and internal state management.
    """

    def __init__(self):
        self._listeners: Dict[str, List[Callable[[ConversionEvent], Awaitable[None]]]] = {}

    def subscribe(self, event_name: str, listener: Callable[[ConversionEvent], Awaitable[None]]):
        """Registers a listener for a specific event."""
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(listener)
        logger.info(f"Subscribed listener to event: {event_name}")

    async def dispatch(self, event: ConversionEvent):
        """Broadcasts an event to all registered listeners."""
        if event.event_name not in self._listeners:
            return

        tasks = [listener(event) for listener in self._listeners[event.event_name]]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.debug(f"Dispatched event: {event.event_name}")

# Global dispatcher instance
event_dispatcher = EventDispatcher()
