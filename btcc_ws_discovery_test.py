"""
One-shot BTCC public WebSocket discovery.
No credentials, cookies, tokens, account access, orders, or retry loop.
Writes no files. Prints handshake, exact request shape, and first response only.
"""

import base64
import hashlib
import os
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

WS_URL = "wss://waccess2.btloginc.com"
CONNECT_TIMEOUT_SECONDS = 12
READ_TIMEOUT_SECONDS = 12

# Public-style probe only. This is intentionally unauthenticated.
# Do not add a sign, token, cookie, account ID, or login message.
SUBSCRIPTION_MESSAGE = (
    '{"id":1002,"method":"kline.query","params":'
    '{"symbol":"BTCUSDT","period":"5m"}}'
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def recv_exact(sock: ssl.SSLSocket, length: int) -> bytes:
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("Socket closed before frame completed.")
        data += chunk
    return data


def decode_frame(sock: ssl.SSLSocket) -> str:
    first, second = recv_exact(sock, 2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F

    if length == 126:
        length = int.from_bytes(recv_exact(sock, 2), "big")
    elif length == 127:
        length = int.from_bytes(recv_exact(sock, 8), "big")

    mask_key = recv_exact(sock, 4) if masked else b""
    payload = recv_exact(sock, length)

    if masked:
        payload = bytes(
            byte ^ mask_key[index % 4]
            for index, byte in enumerate(payload)
        )

    if opcode == 0x8:
        return "WEBSOCKET_CLOSE_FRAME"
    if opcode == 0x9:
        return "WEBSOCKET_PING_FRAME"
    if opcode != 0x1:
        return f"NON_TEXT_FRAME_OPCODE_{opcode}: {payload[:500]!r}"

    return payload.decode("utf-8", errors="replace")


def encode_text_frame(message: str) -> bytes:
    payload = message.encode("utf-8")
    mask_key = os.urandom(4)
    first = bytes([0x81])

    if len(payload) < 126:
        header = bytes([0x80 | len(payload)])
    elif len(payload) <= 0xFFFF:
        header = bytes([0x80 | 126]) + len(payload).to_bytes(2, "big")
    else:
        header = bytes([0x80 | 127]) + len(payload).to_bytes(8, "big")

    masked_payload = bytes(
        byte ^ mask_key[index % 4]
        for index, byte in enumerate(payload)
    )
    return first + header + mask_key + masked_payload


def main() -> int:
    parsed = urlparse(WS_URL)
    host = parsed.hostname
    path = parsed.path or "/"
    port = parsed.port or 443

    nonce = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {nonce}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Origin: https://www.btcc.com\r\n"
        "User-Agent: JHL-BTCC-Public-Discovery/1.0\r\n"
        "\r\n"
    )

    print("BTCC WebSocket One-Shot Discovery")
    print(f"Timestamp UTC: {utc_now()}")
    print(f"URL: {WS_URL}")
    print("Credentials/cookies/tokens: NONE")
    print(f"Exact subscription message: {SUBSCRIPTION_MESSAGE}")

    try:
        raw_socket = socket.create_connection(
            (host, port),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        context = ssl.create_default_context()
        ws_socket = context.wrap_socket(raw_socket, server_hostname=host)
        ws_socket.settimeout(READ_TIMEOUT_SECONDS)

        ws_socket.sendall(request.encode("utf-8"))
        handshake = b""
        while b"\r\n\r\n" not in handshake:
            chunk = ws_socket.recv(4096)
            if not chunk:
                break
            handshake += chunk

        handshake_text = handshake.decode("utf-8", errors="replace")
        first_line = handshake_text.splitlines()[0] if handshake_text else "NO_HANDSHAKE"
        print(f"Handshake result: {first_line}")

        if " 101 " not in first_line:
            print("RESULT: BLOCKED — WebSocket upgrade was not accepted.")
            return 1

        ws_socket.sendall(encode_text_frame(SUBSCRIPTION_MESSAGE))
        response = decode_frame(ws_socket)

        print(f"First response: {response[:2000]}")
        print("RESULT: HANDSHAKE_ACCEPTED — inspect response before calling data public.")
        return 0

    except (OSError, ssl.SSLError, ConnectionError, TimeoutError) as exc:
        print(f"RESULT: BLOCKED — {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
