# fan-out of live messages to the connected browsers

from __future__ import annotations

import asyncio
from typing import Any


class Hub:
  def __init__(self, queue_size: int = 1000) -> None:
    self._subs: set[asyncio.Queue] = set()
    self._queue_size = queue_size

  def subscribe(self) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(self._queue_size)
    self._subs.add(queue)
    return queue

  def unsubscribe(self, queue: asyncio.Queue) -> None:
    self._subs.discard(queue)

  def publish(self, msg: dict[str, Any]) -> None:
    for queue in list(self._subs):
      if queue.full():  # slow client: drop its oldest message rather than block everyone
        queue.get_nowait()
      queue.put_nowait(msg)
