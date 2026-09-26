"""
Optional AI model for the agent chat. Configure ONE of these environment variables and restart:

  OPENAI_API_KEY      (+ optional OPENAI_MODEL, OPENAI_BASE_URL for any OpenAI-compatible service:
                       OpenAI, Groq, OpenRouter, Together, a local Ollama …)
  GEMINI_API_KEY      (+ optional GEMINI_MODEL)
  ANTHROPIC_API_KEY   (+ optional ANTHROPIC_MODEL)

Without a key the agent uses the built-in tutor (core/tutor/engine.py) — no network needed.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_S = int(os.environ.get("AI_TIMEOUT_MS", "30000")) / 1000


def provider() -> dict | None:
    if os.environ.get("OPENAI_API_KEY"):
        return {"id": "openai", "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini")}
    if os.environ.get("GEMINI_API_KEY"):
        return {"id": "gemini", "model": os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")}
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"id": "anthropic", "model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")}
    return None


def configured() -> bool:
    return provider() is not None


def _post(url, headers, body) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"AI provider HTTP {e.code}: {e.read()[:300]!r}") from None


def chat(system: str, history: list[dict], message: str) -> str:
    """history: [{role: 'user' | 'agent', text}] oldest first, NOT including the new message."""
    p = provider()
    if not p:
        raise RuntimeError("No AI provider configured")
    turns = [m for m in [*history[-12:], {"role": "user", "text": message}] if m.get("text")]
    if p["id"] == "openai":
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        d = _post(f"{base}/chat/completions", {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}, {
            "model": p["model"], "temperature": 0.4, "max_tokens": 900,
            "messages": [{"role": "system", "content": system}] + [{"role": "assistant" if m["role"] == "agent" else "user", "content": m["text"]} for m in turns],
        })
        return (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if p["id"] == "gemini":
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(p['model'])}:generateContent"
               f"?key={urllib.parse.quote(os.environ['GEMINI_API_KEY'])}")
        d = _post(url, {}, {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if m["role"] == "agent" else "user", "parts": [{"text": m["text"]}]} for m in turns],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 900},
        })
        parts = (((d.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
        return "".join(x.get("text", "") for x in parts).strip()
    if p["id"] == "anthropic":
        msgs = []  # Anthropic needs strictly alternating roles starting with "user"
        for m in turns:
            role = "assistant" if m["role"] == "agent" else "user"
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n\n" + m["text"]
            else:
                msgs.append({"role": role, "content": m["text"]})
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        d = _post("https://api.anthropic.com/v1/messages", {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                  {"model": p["model"], "max_tokens": 900, "temperature": 0.4, "system": system, "messages": msgs})
        return "".join(x.get("text", "") for x in d.get("content") or []).strip()
    raise RuntimeError("Unknown provider")
