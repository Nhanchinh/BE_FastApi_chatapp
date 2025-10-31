import asyncio
import os
from typing import Awaitable, Callable, Optional


class NoopBus:

    enabled = False

    async def publish(self, channel: str, message: str) -> None:
        return

    async def subscribe(self, channel: str, on_message: Callable[[str], Awaitable[None]]):
        # Return a context manager-like object with an async cancel()
        class _Sub:
            async def run(self):
                await asyncio.Future()
            async def cancel(self):
                return
        return _Sub()

    async def set_presence(self, user_id: str, ttl_seconds: int = 60) -> None:
        return


_bus = None


async def get_bus():
    global _bus
    if _bus is not None:
        return _bus
    url = os.getenv("REDIS_URL")
    if not url:
        _bus = NoopBus()
        return _bus
    try:
        import redis.asyncio as redis  # type: ignore
    except Exception:
        _bus = NoopBus()
        return _bus

    class RedisBus:

        def __init__(self, url: str) -> None:
            self._redis = redis.from_url(url)
            self.enabled = True

        async def publish(self, channel: str, message: str) -> None:
            await self._redis.publish(channel, message)

        async def subscribe(self, channel: str, on_message: Callable[[str], Awaitable[None]]):
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(channel)

            class _Sub:
                _running = True
                async def run(self_inner):
                    while self_inner._running:
                        try:
                            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                            if msg and msg.get("type") == "message":
                                data = msg.get("data")
                                if isinstance(data, bytes):
                                    data = data.decode("utf-8")
                                await on_message(data)  
                        except Exception:
                            await asyncio.sleep(0.5)

                async def cancel(self_inner):
                    self_inner._running = False
                    try:
                        await pubsub.unsubscribe(channel)
                    except Exception:
                        pass

            return _Sub()

        async def set_presence(self, user_id: str, ttl_seconds: int = 60) -> None:
            key = f"presence:{user_id}"
            await self._redis.set(key, "online", ex=ttl_seconds)

    _bus = RedisBus(url)
    return _bus


