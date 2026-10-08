#
# Copyright (c) 2024-2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Frame queue utilities for Pipecat pipeline processors."""

import asyncio
from collections.abc import Callable
from typing import Any

from pipecat.frames.frames import Frame


class FrameQueue(asyncio.Queue):
    """An asyncio.Queue that knows whether any uninterruptible frame is enqueued.

    Extends ``asyncio.Queue`` with ``has_uninterruptible`` and
    ``current_uninterruptible``, so interrupt-handling code can decide whether
    to cancel a task or merely drain the interruptible items, and with
    ``reset()``, which does that draining: it removes every interruptible item
    and keeps the uninterruptible ones (``Frame.interruptible`` False) in place.
    They read the frames' flags as they are at that moment.

    The current item is the one the consumer took last and hasn't marked done
    with ``task_done()``, so consumers that can be cancelled mid-item call it
    in a ``finally``.

    Items may be raw ``Frame`` objects or tuples whose first element is a
    ``Frame`` (e.g. ``(frame, direction, callback)``).  Pass a ``frame_getter``
    callable to extract the frame from each item; the default treats the item
    itself as the frame. Queues that also carry non-frame items should return
    ``None`` from their getter for those.
    """

    def __init__(self, frame_getter: Callable[[Any], Frame | None] = lambda item: item):
        """Initialize the FrameQueue.

        Args:
            frame_getter: Callable that extracts a ``Frame`` from a queue item,
                or ``None`` when the item holds no frame.
                Defaults to the identity function (item is a raw ``Frame``).
                Pass ``lambda item: item[0]`` when items are
                ``(frame, direction, callback)`` tuples.
        """
        super().__init__()
        self._frame_getter = frame_getter
        self._current: Any = None

    def has_frame(self, frame_type: type[Frame]) -> bool:
        """Return True if any frame of the given type is in the queue.

        Note:
            This inspects the internal `_queue` (deque) of asyncio.Queue.
            This is not part of the public API but is stable in CPython.

        Args:
            frame_type: The frame class to check for.

        Returns:
            True if at least one enqueued frame is an instance of ``frame_type``.
        """
        return any(
            isinstance(self._frame_getter(item), frame_type)
            for item in self._queue  # pyright: ignore[reportAttributeAccessIssue]
        )

    @property
    def has_uninterruptible(self) -> bool:
        """Return True if any uninterruptible frame is currently in the queue."""
        # O(n), but it runs only when an interruption is being handled, so its
        # cost is small next to what follows it.
        return any(
            self._is_uninterruptible(item)
            for item in self._queue  # pyright: ignore[reportAttributeAccessIssue]
        )

    @property
    def current_uninterruptible(self) -> bool:
        """Return True if the item the consumer is handling is uninterruptible."""
        return self._current is not None and self._is_uninterruptible(self._current)

    def get_nowait(self) -> Any:
        """Remove and return an item if one is immediately available.

        ``get()`` takes its item through this method too.
        """
        self._current = super().get_nowait()
        return self._current

    def task_done(self) -> None:
        """Mark the current item as done."""
        super().task_done()
        self._current = None

    def reset(self) -> None:
        """Remove all interruptible items, keeping uninterruptible ones."""
        current = self._current
        kept = []
        while not self.empty():
            item = self.get_nowait()
            if self._is_uninterruptible(item):
                kept.append(item)
            self.task_done()
        for item in kept:
            self.put_nowait(item)
        self._current = current

    def _is_uninterruptible(self, item: Any) -> bool:
        frame = self._frame_getter(item)
        return frame is not None and not frame.interruptible


class FramePriorityQueue(FrameQueue, asyncio.PriorityQueue):
    """A priority queue with frame-aware interruption handling.

    Uses the ordering of ``asyncio.PriorityQueue`` and the frame inspection and
    reset operations of ``FrameQueue``. For ``(priority, sequence, frame)`` items,
    pass ``frame_getter=lambda item: item[2]``.
    """
