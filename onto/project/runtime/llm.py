"""LLM 适配层。

MockLLM            —— 按剧本确定性回放，让本体层可以离线测试/演示（CI 友好）
OpenAICompatibleLLM —— urllib 直连任意 OpenAI 兼容端点（DeepSeek/GLM/Qwen/…），零 SDK 依赖

两个类共享同一接口：decide(prompt) -> {"thought", "action", "params"} 或 {"action": "finish", "report"}
"""
from __future__ import annotations

import json
import os
import urllib.request


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").lstrip("JSON").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"LLM 输出中未找到 JSON 对象: {text[:200]!r}")
    return json.loads(text[start:end + 1])


class MockLLM:
    """确定性剧本：steps 依序返回；演完自动 finish。"""

    def __init__(self, script: list):
        self.script = [dict(s) for s in script]
        self.i = 0

    def decide(self, prompt: str) -> dict:
        if self.i >= len(self.script):
            return {"action": "finish", "report": "剧本已执行完毕"}
        step = self.script[self.i]
        self.i += 1
        return dict(step)


class OpenAICompatibleLLM:
    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("ONTO_MODEL", "gpt-4o-mini")

    def decide(self, prompt: str) -> dict:
        payload = json.dumps({
            "model": self.model,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return _extract_json(content)
