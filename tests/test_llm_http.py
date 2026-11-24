"""LocalLLM against a fake OpenAI-compatible server (the shape Ollama,
LM Studio and llama-server answer with)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from newsbot.config import Settings
from newsbot.llm import LocalLLM


class Handler(BaseHTTPRequestHandler):
    requests_seen = []
    reject_json_mode = False

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"data": [{"id": "qwen3.6:35b-a3b"}]})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.requests_seen.append(payload)
        if Handler.reject_json_mode and "response_format" in payload:
            return self._send(400, {"error": "response_format not supported"})
        content = '<think>The guidance raise matters.</think>\n{"direction": 1, "strength": 0.5, ' \
                  '"confidence": 0.75, "horizon_days": 3, "novelty": 0.9, "rationale": "raised guide"}'
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Handler.requests_seen.clear()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_chat_json_roundtrip(server):
    llm = LocalLLM(Settings(llm_base_url=server))
    assert llm.ping() == ["qwen3.6:35b-a3b"]
    out = llm.chat_json("sys", "user")
    assert out["direction"] == 1 and out["confidence"] == 0.75
    sent = Handler.requests_seen[-1]
    assert sent["model"] == "qwen3.6:35b-a3b"
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent["response_format"] == {"type": "json_object"}


def test_falls_back_when_json_mode_rejected(server):
    Handler.reject_json_mode = True
    try:
        out = LocalLLM(Settings(llm_base_url=server)).chat_json("sys", "user")
    finally:
        Handler.reject_json_mode = False
    assert out["direction"] == 1
    assert "response_format" not in Handler.requests_seen[-1]
