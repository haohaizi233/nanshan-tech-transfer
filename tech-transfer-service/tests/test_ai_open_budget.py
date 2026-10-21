import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from modules.ai.chat_runner import post_agent


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_absolute_budget_includes_slow_response_headers_and_connection_close_body(phase):
    received = threading.Event()

    class SlowHeaders(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            received.set()
            try:
                event = {"type": "result", "executionId": "headers-budget", "result": {"success": True, "intent": "out_of_scope", "message": "done", "data": []}}
                body = (json.dumps(event) + "\n").encode()
                if phase == "headers":
                    self.connection.sendall(b"HTTP/1.1 200 OK\r\n")
                    for number in range(10):
                        self.connection.sendall(f"X-Progress-{number}: waiting\r\n".encode())
                        time.sleep(0.1)
                    self.connection.sendall(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
                else:
                    self.connection.sendall(f"HTTP/1.0 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode())
                    for value in body:
                        self.connection.sendall(bytes([value]))
                        time.sleep(0.02)
            except OSError:
                return

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHeaders)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        started = time.monotonic()
        with pytest.raises(Exception) as captured:
            post_agent(f"http://127.0.0.1:{server.server_port}/internal/ai/chat/stream", "test-only", {"executionId": "headers-budget", "message": "hello"}, 0.3, lambda *_args: True)
        elapsed = time.monotonic() - started
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert received.is_set(), f"request did not reach test server: {type(captured.value).__name__}"
    assert elapsed < 0.75, f"response {phase} escaped absolute budget: {elapsed:.3f}s ({type(captured.value).__name__})"
