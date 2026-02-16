from __future__ import annotations
import asyncio
import logging
from telethon import errors

log = logging.getLogger("tg_sync.retry")


class RetryPolicy:
    def __init__(self, max_retries: int = 10, base_sleep: float = 2.0, max_sleep: float = 30.0):
        self.max_retries = max_retries
        self.base_sleep = base_sleep
        self.max_sleep = max_sleep


async def safe_call(coro_factory, *, ctx: str = "", policy: RetryPolicy | None = None):
    """
    coro_factory: () -> coroutine
    FloodWait ждём сколько скажут.
    Timeout/Network ретраим ограниченное число раз.
    """
    policy = policy or RetryPolicy()
    attempt = 0

    while True:
        try:
            if attempt:
                log.warning("retry #%s | %s", attempt, ctx)
            return await coro_factory()

        except errors.FloodWaitError as e:
            wait_s = int(getattr(e, "seconds", 0)) + 1
            log.warning("FloodWait %ss | %s", wait_s, ctx)
            await asyncio.sleep(wait_s)

        except (asyncio.TimeoutError, TimeoutError, OSError, ConnectionError) as e:
            attempt += 1
            if attempt > policy.max_retries:
                log.error("give up after %s retries | %s | %s: %s", policy.max_retries, ctx, type(e).__name__, e)
                raise
            sleep_s = min(policy.max_sleep, policy.base_sleep * attempt)
            log.warning("%s: sleep %ss | %s", type(e).__name__, sleep_s, ctx)
            await asyncio.sleep(sleep_s)
