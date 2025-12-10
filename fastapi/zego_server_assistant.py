import json
import time
import struct
import base64
import random
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


class ServerAssistant:
    """
    Official-like implementation to generate Zego token (version 04).
    """

    def generate_token(self, app_id, signature, device_id, expiry, payload=""):
        token_info = {
            "app_id": app_id,
            "user_id": device_id,
            "nonce": random.randint(100000, 999999),
            "ctime": int(time.time()),
            "expire": int(time.time()) + expiry,
            "payload": payload or "",
        }

        plain_text = json.dumps(token_info)

        iv = bytes([random.randint(0, 255) for _ in range(16)])

        key = signature[:32] if len(signature) > 32 else signature.ljust(32, "0")
        cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(pad(plain_text.encode("utf-8"), AES.block_size))

        final_binary = struct.pack(">QH", token_info["expire"], len(iv)) + iv + struct.pack(
            ">H", len(encrypted)
        ) + encrypted

        return f"04{base64.b64encode(final_binary).decode('utf-8')}"

