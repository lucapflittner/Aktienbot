"""Client for a LOCAL language model behind an OpenAI-compatible endpoint.

Works with Ollama (default http://localhost:11434/v1), LM Studio
(http://localhost:1234/v1), llama.cpp's llama-server and vLLM. Nothing leaves
your machine.
"""
import json
import os
import re

import requests

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply. Tolerates reasoning
    blocks, ```json fences and chatter before/after the object."""
    text = THINK_BLOCK.sub("", text or "")
    text = re.sub(r"^.*?</think>", "", text, flags=re.S)  # unclosed opening tag
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        raise LLMError(f"no JSON object in reply: {text[:200]!r}")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise LLMError(f"unterminated JSON in reply: {text[:200]!r}")


class LocalLLM:
    def __init__(self, settings):
        self.s = settings
        self.thinking = os.environ.get("LLM_THINKING", "0") == "1"
        self.json_mode = os.environ.get("LLM_JSON_MODE", "json_object")

    @property
    def name(self) -> str:
        return self.s.llm_model

    def ping(self) -> list:
        """List models the server offers -- a cheap 'is it running?' check."""
        r = requests.get(self.s.llm_base_url.rstrip("/") + "/models",
                         headers={"Authorization": f"Bearer {self.s.llm_api_key}"}, timeout=10)
        r.raise_for_status()
        return [m.get("id") for m in r.json().get("data", [])]

    def chat_json(self, system: str, user: str, max_tokens: int = 800) -> dict:
        payload = {
            "model": self.s.llm_model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": self.s.llm_temperature,
            "max_tokens": max_tokens if not self.thinking else max_tokens + 4000,
            # Qwen3-family hybrid models: switch reasoning off for fast,
            # cheap classification (honoured by vLLM / llama.cpp; Ollama
            # ignores unknown fields, the <think> stripping covers the rest).
            "chat_template_kwargs": {"enable_thinking": self.thinking},
        }
        if self.json_mode == "json_object":
            payload["response_format"] = {"type": "json_object"}
        url = self.s.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.s.llm_api_key}"}
        r = requests.post(url, json=payload, headers=headers, timeout=self.s.llm_timeout_s)
        if r.status_code == 400 and "response_format" in payload:
            # some servers (older LM Studio) reject json_object - retry without
            payload.pop("response_format")
            r = requests.post(url, json=payload, headers=headers, timeout=self.s.llm_timeout_s)
        if r.status_code != 200:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
        content = r.json()["choices"][0]["message"].get("content") or ""
        return extract_json(content)
