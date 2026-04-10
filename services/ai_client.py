"""
Gemini API client: model factory, JSON repair, and rate-limited generation.
"""
import os
import json
import time
from pathlib import Path
import google.generativeai as genai

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise EnvironmentError("GEMINI_API_KEY is not set. Add it to your .env file.")

# Per-tier model selection. GEMINI_MODEL is the legacy fallback for "fast".
MODELS = {
    "fast":      os.environ.get("GEMINI_MODEL_FAST",      os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")),
    "quality":   os.environ.get("GEMINI_MODEL_QUALITY",   "gemini-2.5-flash"),
    "reasoning": os.environ.get("GEMINI_MODEL_REASONING", "gemini-2.5-flash"),
}

print(f"[AI] Initializing Gemini API")
print(f"[AI] Models — fast: {MODELS['fast']} | quality: {MODELS['quality']}")
genai.configure(api_key=GEMINI_API_KEY)

# Cache model instances keyed by (tier, system_instruction) so we don't
# construct a new GenerativeModel on every call.
_model_cache: dict = {}


def get_model(tier: str = "fast", system_instruction: str | None = None) -> genai.GenerativeModel:
    """Return a cached GenerativeModel for the given tier and optional system instruction."""
    key = (tier, system_instruction)
    if key not in _model_cache:
        kwargs: dict = {}
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        _model_cache[key] = genai.GenerativeModel(MODELS[tier], **kwargs)
    return _model_cache[key]


def robust_json_parse(text: str):
    """
    Parse JSON from LLM output.
    1. Try json.loads directly.
    2. Try json-repair (handles truncation, missing commas, etc.).
    3. Fall back to structural brace-balancing.
    Raises ValueError if all attempts fail.
    """
    text = text.strip()
    # Strip leading non-JSON text
    start = text.find("{")
    if start != -1:
        text = text[start:]

    # Attempt 1: clean parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # Attempt 2: json-repair library
    try:
        from json_repair import repair_json  # pip install json-repair
        return json.loads(repair_json(text))
    except ImportError:
        print("[AI] WARNING: json-repair not installed. Run: pip install json-repair")
    except Exception:
        pass

    # Attempt 3: naive structural close
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


def safe_generate_content(
    prompt_content,
    config: dict | None = None,
    is_json: bool = False,
    max_retries: int = 5,
    tier: str = "fast",
    model=None,
):
    """
    Call model.generate_content with exponential back-off on 429s.

    Pass `model` to use a specific instance (e.g. one with a system instruction).
    Pass `tier` to pick from the MODELS registry when no model is provided.
    Raises on unrecoverable failure instead of returning an error dict.
    """
    if model is None:
        model = get_model(tier)

    gen_config = dict(config) if config else {"max_output_tokens": 8192, "temperature": 0.4}
    if is_json:
        gen_config["response_mime_type"] = "application/json"

    base_delay = 5
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt_content, generation_config=gen_config)
            return robust_json_parse(response.text) if is_json else response.text
        except ValueError:
            # JSON parse failure — the API call itself succeeded, retrying won't help.
            raise
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"[CRITICAL] AI Service failed after {max_retries} attempts: {e}")
                raise
            if "429" in str(e):
                sleep_time = base_delay * (2 ** attempt)
                print(f"[RETRY] Rate limited (429). Retrying in {sleep_time}s... ({attempt+1}/{max_retries})")
                time.sleep(sleep_time)
            else:
                print(f"[RETRY] AI Error: {e}. Retrying in 2s...")
                time.sleep(2)
