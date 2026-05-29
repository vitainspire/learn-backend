"""
OpenRouter API client: replaces the previous Google Gemini SDK.
All text-generation calls now go through the OpenRouter REST API.
"""
import os
import json
import time
import base64
import io
import requests
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    raise EnvironmentError("OPENROUTER_API_KEY is not set. Add it to your .env file.")

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Per-tier model selection. Override via env vars if needed.
MODELS = {
    "fast":      os.environ.get("OPENROUTER_MODEL_FAST",      os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")),
    "quality":   os.environ.get("OPENROUTER_MODEL_QUALITY",   "google/gemini-2.5-flash"),
    "reasoning": os.environ.get("OPENROUTER_MODEL_REASONING", "google/gemini-2.5-flash"),
}

print(f"[AI] Initializing OpenRouter API")
print(f"[AI] Models — fast: {MODELS['fast']} | quality: {MODELS['quality']}")

_model_cache: dict = {}


def get_model(tier: str = "fast", system_instruction: str | None = None) -> dict:
    """Return a config dict for the given tier. Kept for backward compatibility."""
    key = (tier, system_instruction)
    if key not in _model_cache:
        _model_cache[key] = {"tier": tier, "system_instruction": system_instruction}
    return _model_cache[key]


def _pil_to_base64_url(image) -> str:
    """Convert a PIL Image to a base64 JPEG data URL."""
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"


def _build_messages(
    prompt_content,
    system_instruction: str | None = None,
    is_json: bool = False,
) -> list:
    """Convert a prompt (string or list of strings/PIL images) into OpenRouter messages."""
    messages = []

    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    elif is_json:
        messages.append({
            "role": "system",
            "content": "You must respond with valid JSON only. No markdown fences, no preamble.",
        })

    if isinstance(prompt_content, str):
        messages.append({"role": "user", "content": prompt_content})
    elif isinstance(prompt_content, list):
        parts = []
        for item in prompt_content:
            if isinstance(item, str):
                parts.append({"type": "text", "text": item})
            else:
                # Assume PIL Image
                try:
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": _pil_to_base64_url(item)},
                    })
                except Exception as e:
                    print(f"[AI] Warning: failed to encode image: {e}")
        # Flatten to plain text if there are no images
        if all(p["type"] == "text" for p in parts):
            messages.append({"role": "user", "content": "\n".join(p["text"] for p in parts)})
        else:
            messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": str(prompt_content)})

    return messages


def robust_json_parse(text: str):
    """
    Parse JSON from LLM output.
    1. Strip markdown fences.
    2. Try json.loads directly.
    3. Try json-repair.
    4. Fall back to structural brace-balancing.
    Raises ValueError if all attempts fail.
    """
    if not text:
        raise ValueError("Cannot parse JSON from empty/null response")
    text = text.strip()
    # Strip markdown fences
    for prefix in ("```json", "```"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

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
        snippet = text[:200].encode('ascii', errors='replace').decode('ascii')
        print(f"[AI] JSON Parse CRITICAL FAILURE: {e}. Snippet: {snippet}...")
        raise ValueError("JSON parse failed — check AI output for malformed JSON") from e


def safe_generate_content(
    prompt_content,
    config: dict | None = None,
    is_json: bool = False,
    max_retries: int = 5,
    tier: str = "fast",
    model=None,
):
    """
    Send a prompt to OpenRouter with exponential back-off on 429s.

    prompt_content: str, or list that may include PIL Images for vision calls.
    model: dict from get_model() — overrides tier/system_instruction when provided.
    """
    system_instruction = None
    if isinstance(model, dict):
        tier = model.get("tier", tier)
        system_instruction = model.get("system_instruction")

    model_name = MODELS.get(tier, MODELS["fast"])
    gen_config = dict(config) if config else {"max_output_tokens": 8192, "temperature": 0.4}

    messages = _build_messages(
        prompt_content,
        system_instruction=system_instruction,
        is_json=is_json,
    )

    payload = {
        "model": model_name,
        "messages": messages,
        "max_tokens": gen_config.get("max_output_tokens", 8192),
        "temperature": gen_config.get("temperature", 0.4),
    }

    base_delay = 5
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                _OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            msg  = resp.json()["choices"][0]["message"]
            text = msg.get("content")

            # Reasoning models (e.g. nemotron) may return null content and put
            # the actual response inside reasoning_details[0].text or reasoning.
            if not text:
                rd = msg.get("reasoning_details") or []
                if rd and isinstance(rd, list):
                    text = rd[0].get("text") or rd[0].get("content") or ""
            if not text:
                text = msg.get("reasoning") or ""

            if not text:
                raise ValueError("Model returned empty content — check the OpenRouter model supports text output.")

            return robust_json_parse(text) if is_json else text
        except ValueError:
            # JSON parse failure — retrying won't help.
            raise
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"[CRITICAL] AI Service failed after {max_retries} attempts: {e}")
                raise
            err = str(e)
            if "429" in err:
                sleep_time = base_delay * (2 ** attempt)
                print(f"[RETRY] Rate limited (429). Retrying in {sleep_time}s... ({attempt+1}/{max_retries})")
                time.sleep(sleep_time)
            else:
                print(f"[RETRY] AI Error: {e}. Retrying in 2s...")
                time.sleep(2)
