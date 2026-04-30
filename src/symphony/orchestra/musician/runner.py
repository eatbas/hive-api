from __future__ import annotations

import asyncio
import logging

from ...shells import ShellSessionError
from ..score import ScoreHandle, _safe_error_message
from ...models.enums import ScoreStatus

logger = logging.getLogger("symphony.musician")


class _RunnerMixin:
    """Supervisor + queue loop behaviour for :class:`Musician`.

    Implements the worker task that drains the score queue and the
    supervisor that respawns the worker if it ever dies outside of an
    intentional :meth:`Musician.stop`. Relies on the following
    attributes provided by the host class: ``provider``, ``model``,
    ``queue``, ``busy``, ``_runner_task``, ``_current_handle``,
    ``_stopping``, and the executor method ``_dispatch_score``.
    """

    def _ensure_runner_alive(self) -> None:
        """Spawn or respawn the worker task that drains :attr:`queue`.

        The runner is supposed to live for the entire musician lifetime,
        only exiting when :meth:`stop` cancels it. In practice race
        conditions on Windows shell teardown or unexpected exceptions
        inside the inner loop have killed the task in the past, leaving
        queued scores stranded with no consumer.

        This method is the supervisor: it inspects ``_runner_task`` and
        starts a fresh one whenever the previous task is missing or has
        finished outside of an intentional stop. The death reason is
        logged so we can diagnose recurring failures.
        """
        if self._stopping:
            return
        task = self._runner_task
        if task is not None and not task.done():
            return
        if task is not None:
            try:
                exc = task.exception()
            except (asyncio.CancelledError, asyncio.InvalidStateError):
                exc = None
            if exc is not None:
                logger.error(
                    "Musician %s/%s runner died unexpectedly (%s) -- restarting",
                    self.provider.value,
                    self.model,
                    exc,
                    exc_info=exc,
                )
            else:
                logger.warning(
                    "Musician %s/%s runner exited without stop() being called -- restarting",
                    self.provider.value,
                    self.model,
                )
        self._runner_task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        """Drain the score queue until :meth:`stop` cancels this task.

        The loop is wrapped so that a single buggy iteration can never
        kill the worker -- otherwise queued scores would sit forever
        waiting for a consumer that no longer exists. Only
        :class:`asyncio.CancelledError` (raised by ``stop()``) is
        allowed to break out of the loop.
        """
        while True:
            try:
                request, handle = await self.queue.get()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - asyncio internal
                logger.exception(
                    "Musician %s/%s queue.get() failed: %s -- continuing",
                    self.provider.value,
                    self.model,
                    exc,
                )
                # Avoid a tight loop if the queue is in a persistent bad state.
                await asyncio.sleep(0.5)
                continue

            self.busy = True
            queue_marked_done = False
            try:
                await self._dispatch_score(request, handle)
            except asyncio.CancelledError:
                # Re-queue the score so the next runner picks it up and
                # publish it to the caller, then propagate the cancel
                # so stop() can finish cleanly.
                await self._fail_handle_safely(
                    handle,
                    "Musician runner was cancelled before the score completed",
                )
                raise
            except BaseException as exc:  # noqa: BLE001 - last-resort safety net
                # Anything that escapes _dispatch_score is a bug. Surface
                # it to the score so the caller fails fast instead of
                # waiting forever, log the trace, and keep the loop alive.
                logger.exception(
                    "Musician %s/%s unexpected error while running %s: %s",
                    self.provider.value,
                    self.model,
                    handle.score_id,
                    exc,
                )
                await self._fail_handle_safely(handle, _safe_error_message(exc))
            finally:
                self._current_handle = None
                self.busy = False
                if not queue_marked_done:
                    try:
                        self.queue.task_done()
                    except ValueError:
                        # Already marked done somewhere else; safe to ignore.
                        pass

    async def _fail_handle_safely(self, handle: ScoreHandle, error_msg: str) -> None:
        """Publish a failure event for ``handle`` without raising further.

        Used by the supervisor's last-resort exception handler so a
        broken score never leaves its caller waiting on a future that
        will never resolve.
        """
        try:
            self.last_error = error_msg
            if handle.status not in {ScoreStatus.COMPLETED, ScoreStatus.FAILED, ScoreStatus.STOPPED}:
                handle.status = ScoreStatus.FAILED
            await handle.publish(
                {
                    "type": "failed",
                    "error": error_msg,
                    "provider": self.provider.value,
                    "model": self.model,
                }
            )
            if handle.result_future is not None and not handle.result_future.done():
                handle.reject(ShellSessionError(error_msg))
        except Exception:  # pragma: no cover - publish should never raise
            logger.exception(
                "Musician %s/%s failed to publish error for score %s",
                self.provider.value,
                self.model,
                handle.score_id,
            )
