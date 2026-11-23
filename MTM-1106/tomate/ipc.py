"""Socket Unix local entre o daemon e a GUI (mensagens JSON, uma por linha)."""
from __future__ import annotations

import json
import os
import socket


def socket_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/tomate-{os.getuid()}"
    os.makedirs(base, mode=0o700, exist_ok=True)
    return os.path.join(base, "tomate.sock")


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode()


def request(msg: dict, timeout: float = 2.0) -> dict | None:
    """Envia um comando e espera uma resposta. Devolve None se o daemon não estiver rodando."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(socket_path())
            s.sendall(encode(msg))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            return json.loads(buf) if buf else None
    except (OSError, ValueError):
        return None
