"""
OpenRouter API client: model selection, JSON repair, and rate-limited generation.

OpenRouter is OpenAI-compatible — all AI calls funnel through here.

Default tier → model mapping (override any tier via env var):
  fast      → google/gemini-2.5-flash   (paid, fast + multimodal)
  quality   → google/gemini-2.5-flash   (paid, best JSON quality)
  reasoning → google/gemini-2.5-flash   (paid, strong reasoning)
  vision    → google/gemini-2.5-flash   (paid, image+text)
"""
import os
import json
import time
import base64
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
except ImportError:
    pass

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
if not OPENROUTER_API_KEY:
    raise EnvironmentError("OPENROUTER_API_KEY is not set. Add it to your .env file.")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MODELS = {
    "fast":      os.environ.get("OPENROUTER_MODEL_FAST",      "deepseek/deepseek-v4-flash:free"),
    "quality":   os.environ.get("OPENROUTER_MODEL_QUALITY",   "nvidia/nemotron-3-super-120b-a12b:free"),
    "reasoning": os.environ.get("OPENROUTER_MODEL_REASONING", "nvidia/nemotron-3-super-120b-a12b:free"),
    "vision":    os.environ.get("OPENROUTER_MODEL_VISION",    "moonshotai/kimi-k2.6:free"),
}

print(f"[AI] OpenRouter client ready")
print(f"[AI] fast={MODELS['fast']} | quality={MODELS['quality']} | vision={MODELS['vision']}")


def robust_json_parse(text: str):
    """
    Parse JSON from LLM output.
    1. Try json.loads directly.
    2. Try json-repair (handles truncation, missing commas, etc.).
    3. Fall back to structural brace-balancing.
    Raises ValueError if all attempts fail.
    """
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        text = text.lstrip("`").lstrip("json").strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    start = text.find("{")
    if start != -1:
        text = text[start:]

    try:
        return json.loads(text)
    except Exception:
        pass

    try:
        from json_repair import repair_json
        return json.loads(repair_json(text))
    except ImportError:
        print("[AI] WARNING: json-repair not installed. Run: pip install json-repair")
    except Exception:
        pass

    print("[AI] JSON Parse Warning: attempting structural brace repair...")
    temp = text
    if temp.count('"') % 2 != 0:
        temp += '"'
    open_braces = temp.count("{") - temp.count("}")
    if open_braces > 0:
        temp += "}" * open_braces
    open_brackets = temp.count("[") - temp.count("]")
    if open_brackets > 0:
        temp += "]" * open_brackets

    try:
        return json.loads(temp)
    except Exception as e:
        print(f"[AI] JSON Parse CRITICAL FAILURE: {e}. Snippet: {text[:200]}...")
        raise ValueError("JSON parse failed — check AI output for malformed JSON") from e


def _build_user_content(prompt_content, image_bytes: bytes | None = None):
    """
    Convert prompt_content into an OpenRouter message content value.
    Returns a plain string for text-only calls, or a list of parts for multimodal calls.
    Handles both plain strings and Gemini-style parts lists transparently.
    """
    if isinstance(prompt_content, str):
        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode()
            return [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": prompt_content},
            ]
        return prompt_content

    if isinstance(prompt_content, list):
        # Gemini-style parts: [{"mime_type": ..., "data": bytes}, "text_str", ...]
        parts = []
        text_chunks = []
        for item in prompt_content:
            if isinstance(item, dict) and "mime_type" in item and "data" in item:
                b64 = base64.b64encode(item["data"]).decode()
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{item['mime_type']};base64,{b64}"},
                })
            elif isinstance(item, str):
                text_chunks.append(item)
        if text_chunks:
            parts.append({"type": "text", "text": "\n".join(text_chunks)})
        return parts if parts else str(prompt_content)

    return str(prompt_content)


def _call_openrouter(
    messages: list[dict],
    model_id: str,
    max_tokens: int = 8192,
    temperature: float = 0.4,
    json_mode: bool = False,
    max_retries: int = 5,
) -> str:
    """Raw OpenRouter HTTP call with exponential back-off on 429s."""
    import requests

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    base_delay = 5
    for attempt in range(max_retries):
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            status = None
            if hasattr(e, "response") and e.response is not None:
                status = e.response.status_code
            # 402 / 401 are account issues — retrying never helps, fail immediately
            if status in (401, 402) or "402" in str(e) or "401" in str(e):
                msg = "402 Payment Required" if status == 402 else "401 Unauthorized"
                print(f"[CRITICAL] OpenRouter {msg} — check your account balance or API key.")
                raise RuntimeError(f"OpenRouter {msg}: add credits at openrouter.ai or verify your API key.") from e
            if attempt == max_retries - 1:
                print(f"[CRITICAL] OpenRouter failed after {max_retries} attempts: {e}")
                raise
            if status == 429 or "429" in str(e):
                delay = base_delay * (2 ** attempt)
                print(f"[RETRY] Rate limited (429). Retrying in {delay}s... ({attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                print(f"[RETRY] OpenRouter error: {e}. Retrying in 2s...")
                time.sleep(2)
    return ""


def safe_generate_content(
    prompt_content,
    config: dict | None = None,
    is_json: bool = False,
    max_retries: int = 5,
    tier: str = "fast",
    model=None,
    system_instruction: str | None = None,
    image_bytes: bytes | None = None,
):
    """
    Generate content via OpenRouter. Drop-in replacement for the Gemini safe_generate_content.

    Args:
        prompt_content: str prompt or Gemini-style parts list (for vision).
        config: dict with max_output_tokens and temperature.
        is_json: request JSON output and return a parsed dict.
        tier: "fast" | "quality" | "reasoning" | "vision"
        model: _ModelProxy from get_model(); uses its tier + system_instruction.
        system_instruction: optional system prompt (ignored when model proxy is supplied).
        image_bytes: raw PNG/JPEG bytes attached as a vision input.
    """
    if model is not None and isinstance(model, _ModelProxy):
        gen_config = dict(config or {})
        if is_json:
            gen_config["response_mime_type"] = "application/json"
        response = model.generate_content(prompt_content, generation_config=gen_config)
        return robust_json_parse(response.text) if is_json else response.text

    cfg = config or {"max_output_tokens": 8192, "temperature": 0.4}
    model_id = MODELS.get(tier, MODELS["fast"])

    messages: list[dict] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": _build_user_content(prompt_content, image_bytes)})

    text = _call_openrouter(
        messages,
        model_id=model_id,
        max_tokens=cfg.get("max_output_tokens", 8192),
        temperature=cfg.get("temperature", 0.4),
        json_mode=is_json,
        max_retries=max_retries,
    )
    return robust_json_parse(text) if is_json else text


def get_model(tier: str = "fast", system_instruction: str | None = None) -> "_ModelProxy":
    """Return a model proxy for the given tier and optional system instruction."""
    return _ModelProxy(tier=tier, system_instruction=system_instruction)


class _ModelProxy:
    """
    Drop-in replacement for genai.GenerativeModel.
    Code that does model.generate_content(prompt, generation_config={...}) works unchanged.
    """
    def __init__(self, tier: str = "fast", system_instruction: str | None = None):
        self.tier = tier
        self.system_instruction = system_instruction

    def generate_content(self, prompt_content, generation_config: dict | None = None):
        cfg = generation_config or {}
        is_json = cfg.get("response_mime_type") == "application/json"

        messages: list[dict] = []
        if self.system_instruction:
            messages.append({"role": "system", "content": self.system_instruction})
        messages.append({"role": "user", "content": _build_user_content(prompt_content)})

        text = _call_openrouter(
            messages,
            model_id=MODELS.get(self.tier, MODELS["fast"]),
            max_tokens=cfg.get("max_output_tokens", 8192),
            temperature=cfg.get("temperature", 0.4),
            json_mode=is_json,
        )
        return _ResponseProxy(text)


class _ResponseProxy:
    """Wraps raw text so response.text works like Gemini's response object."""
    def __init__(self, content: str):
        self._content = content or ""
        self.candidates = [_CandidateProxy()]

    @property
    def text(self):
        return self._content


class _CandidateProxy:
    """Stub so code checking candidate.finish_reason == 4 doesn't raise AttributeError."""
    finish_reason = None
