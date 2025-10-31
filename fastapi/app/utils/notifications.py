import os
from typing import List


class NoopPush:

    enabled = False

    async def send_fcm(self, tokens: List[str], title: str, body: str, data: dict | None = None) -> None:
        return


_push = None


async def get_push():
    global _push
    if _push is not None:
        return _push
    server_key = os.getenv("FCM_SERVER_KEY")
    if not server_key:
        _push = NoopPush()
        return _push
    try:
        from pyfcm import FCMNotification  # type: ignore
    except Exception:
        _push = NoopPush()
        return _push

    class FcmPush:

        def __init__(self, key: str) -> None:
            self._client = FCMNotification(api_key=key)
            self.enabled = True

        async def send_fcm(self, tokens: List[str], title: str, body: str, data: dict | None = None) -> None:
            if not tokens:
                return
            # pyfcm is sync; run in thread if needed. For simplicity, call directly.
            try:
                self._client.notify_multiple_devices(registration_ids=tokens, message_title=title, message_body=body, data_message=data or {})
            except Exception:
                pass

    _push = FcmPush(server_key)
    return _push


