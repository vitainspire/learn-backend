"""
Image generation for worksheet questions.

Generation strategy (tried in order, first success wins):
  1. Hugging Face FLUX.1-schnell  — primary (free, fast)
  2. Gemini image model           — fallback if HF fails
  3. Replicate FLUX Schnell       — fallback (50 free/month)
  4. Stability AI SD3             — fallback (25 free/month)
  5. Pollinations.ai              — last resort (no key required)

The caller (enrich_worksheet_with_images) never raises — every failure is
logged and skipped so the worksheet is always returned intact.
"""

import os
import base64
import time
import asyncio
import httpx
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

try:
    from huggingface_hub import InferenceClient
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False
    print("[IMAGE] huggingface_hub not installed — HF provider disabled.")

_HF_TOKEN  = os.environ.get("HF_TOKEN", "")
_HF_MODEL  = "black-forest-labs/FLUX.1-schnell"
_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
_G_BASE    = "https://generativelanguage.googleapis.com/v1beta/models"
# Primary Gemini image model — generateContent API
_G_MODEL   = "gemini-2.5-flash-image"
# Imagen 4 Fast — predict API (higher quality, same key)
_IMAGEN_MODEL = "imagen-4.0-fast-generate-001"

_STYLE = (
    "cartoon style, flat illustration, child-friendly educational art, "
    "bright colours, white background, no text, no words, no letters"
)

# Gemini probe cache with TTL so a transient failure doesn't permanently
# disable it for the process lifetime.
_gemini_available: bool | None = None
_gemini_probe_ts: float = 0.0
_GEMINI_PROBE_TTL = 300  # re-probe after 5 minutes

# Rate limiting to avoid 429 errors
_last_request_time = {}
_MIN_REQUEST_INTERVAL = 2.0  # seconds between requests per provider


async def _rate_limit(provider: str):
    """Ensure minimum time between requests to avoid rate limits."""
    now = time.time()
    last = _last_request_time.get(provider, 0)
    wait = _MIN_REQUEST_INTERVAL - (now - last)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request_time[provider] = time.time()


# ── Gemini ────────────────────────────────────────────────────────────────────

async def _gemini_probe() -> bool:
    """
    Lightweight probe: GET the model metadata — no image tokens consumed.
    Succeeds only on HTTP 200 so a missing key or wrong model name fails fast.
    """
    global _gemini_available, _gemini_probe_ts
    now = time.monotonic()
    if _gemini_available is True:
        return True
    if _gemini_available is False and (now - _gemini_probe_ts) < _GEMINI_PROBE_TTL:
        return False

    if not _API_KEY:
        _gemini_available = False
        _gemini_probe_ts = now
        return False

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{_G_BASE}/{_G_MODEL}?key={_API_KEY}", timeout=10
            )
            _gemini_available = r.status_code == 200
    except Exception:
        _gemini_available = False

    _gemini_probe_ts = now
    print(f"[IMAGE] Gemini probe ({_G_MODEL}): {'OK' if _gemini_available else 'FAILED'}")
    return _gemini_available


async def _gemini_generate(prompt: str, save_path: Path) -> bool:
    if not await _gemini_probe():
        return False
    url = f"{_G_BASE}/{_G_MODEL}:generateContent?key={_API_KEY}"
    body = {
        "contents": [{"parts": [{"text": f"{prompt}, {_STYLE}"}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=body, timeout=45)
            if r.status_code != 200:
                # Force re-probe next time so transient 5xx doesn't permanently
                # mark Gemini as unavailable
                global _gemini_available, _gemini_probe_ts
                _gemini_available = None
                _gemini_probe_ts = 0.0
                return False
            for part in (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", []):
                if "inlineData" in part:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(base64.b64decode(part["inlineData"]["data"]))
                    return True
        return False
    except Exception as e:
        print(f"[IMAGE] Gemini request error: {e}")
        return False


# ── Imagen 4 Fast (same API key, predict endpoint) ───────────────────────────

async def _imagen4_generate(prompt: str, save_path: Path) -> bool:
    if not _API_KEY:
        return False
    url = f"{_G_BASE}/{_IMAGEN_MODEL}:predict?key={_API_KEY}"
    body = {
        "instances": [{"prompt": f"{prompt}, {_STYLE}"}],
        "parameters": {"sampleCount": 1},
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=body, timeout=45)
            if r.status_code != 200:
                print(f"[IMAGE] Imagen4 returned {r.status_code}: {r.text[:120]}")
                return False
            preds = r.json().get("predictions", [])
            for pred in preds:
                b64 = pred.get("bytesBase64Encoded")
                if b64:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    save_path.write_bytes(base64.b64decode(b64))
                    print(f"[IMAGE] Imagen4 OK: {save_path.name}")
                    return True
        return False
    except Exception as e:
        print(f"[IMAGE] Imagen4 error: {e}")
        return False


# ── Hugging Face ──────────────────────────────────────────────────────────────

async def _huggingface_generate(prompt: str, save_path: Path, retries: int = 2) -> bool:
    if not HF_AVAILABLE:
        return False
    if not _HF_TOKEN:
        print("[IMAGE] HF_TOKEN not set — skipping Hugging Face")
        return False

    await _rate_limit("huggingface")
    client = InferenceClient(api_key=_HF_TOKEN)
    full_prompt = f"{prompt}, {_STYLE}"

    for attempt in range(1, retries + 1):
        try:
            print(f"[IMAGE] HuggingFace attempt {attempt}/{retries}…")
            pil_image = await asyncio.to_thread(
                client.text_to_image,
                full_prompt,
                model=_HF_MODEL,
                width=512,
                height=512,
            )
            save_path.parent.mkdir(parents=True, exist_ok=True)
            pil_image.save(str(save_path), "PNG")
            print(f"[IMAGE] HuggingFace OK: {save_path.name}")
            return True
        except Exception as e:
            error_str = str(e)
            print(f"[IMAGE] HuggingFace attempt {attempt}/{retries} failed: {e}")
            # Don't retry on 402 (payment required) - it won't succeed
            if "402" in error_str or "Payment Required" in error_str:
                print("[IMAGE] HuggingFace credits depleted, skipping retries")
                return False
            if attempt < retries:
                await asyncio.sleep(2 * attempt)

    return False


# ── Pollinations.ai (no API key required) ────────────────────────────────────

async def _pollinations_generate(prompt: str, save_path: Path) -> bool:
    await _rate_limit("pollinations")
    import urllib.parse
    encoded = urllib.parse.quote(f"{prompt}, {_STYLE}")
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=512&height=512&nologo=true"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=60, follow_redirects=True)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(r.content)
                print(f"[IMAGE] Pollinations OK: {save_path.name}")
                return True
            print(f"[IMAGE] Pollinations returned {r.status_code}")
            return False
    except Exception as e:
        print(f"[IMAGE] Pollinations error: {e}")
        return False


# ── Replicate (free tier available) ──────────────────────────────────────────

async def _replicate_generate(prompt: str, save_path: Path) -> bool:
    """
    Uses Replicate's FLUX Schnell model via their API.
    Requires REPLICATE_API_TOKEN in environment.
    Free tier: 50 predictions/month
    """
    token = os.environ.get("REPLICATE_API_TOKEN", "")
    if not token:
        return False
    
    try:
        async with httpx.AsyncClient() as client:
            # Create prediction
            r = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "version": "5599ed30703defd1d160a25a63321b4dec97101d98b4674bcc56e41f62f35637",
                    "input": {
                        "prompt": f"{prompt}, {_STYLE}",
                        "width": 512,
                        "height": 512,
                        "num_outputs": 1,
                    }
                },
                timeout=10,
            )
            
            if r.status_code != 201:
                print(f"[IMAGE] Replicate create failed: {r.status_code}")
                return False
            
            prediction_url = r.json()["urls"]["get"]
            
            # Poll for completion (max 60s)
            for _ in range(30):
                await asyncio.sleep(2)
                status_r = await client.get(
                    prediction_url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                
                if status_r.status_code != 200:
                    return False
                
                data = status_r.json()
                if data["status"] == "succeeded":
                    image_url = data["output"][0]
                    img_r = await client.get(image_url, timeout=30)
                    if img_r.status_code == 200:
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        save_path.write_bytes(img_r.content)
                        print(f"[IMAGE] Replicate OK: {save_path.name}")
                        return True
                elif data["status"] in ("failed", "canceled"):
                    print(f"[IMAGE] Replicate prediction {data['status']}")
                    return False
            
            print("[IMAGE] Replicate timeout")
            return False
            
    except Exception as e:
        print(f"[IMAGE] Replicate error: {e}")
        return False


# ── Stability AI (free tier available) ───────────────────────────────────────

async def _stability_generate(prompt: str, save_path: Path) -> bool:
    """
    Uses Stability AI's SD3 model.
    Requires STABILITY_API_KEY in environment.
    Free tier: 25 credits/month
    """
    api_key = os.environ.get("STABILITY_API_KEY", "")
    if not api_key:
        return False
    
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.stability.ai/v2beta/stable-image/generate/sd3",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "image/*",
                },
                files={
                    "prompt": (None, f"{prompt}, {_STYLE}"),
                    "output_format": (None, "png"),
                    "aspect_ratio": (None, "1:1"),
                },
                timeout=60,
            )
            
            if r.status_code == 200:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(r.content)
                print(f"[IMAGE] Stability OK: {save_path.name}")
                return True
            else:
                print(f"[IMAGE] Stability returned {r.status_code}")
                return False
                
    except Exception as e:
        print(f"[IMAGE] Stability error: {e}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_image(prompt: str, save_path: Path) -> bool:
    """
    Fallback chain (first success wins):
      HuggingFace → Gemini 2.5 Flash Image → Imagen 4 Fast
      → Replicate → Stability AI → Pollinations.ai
    """
    print(f"[IMAGE] Generating: {prompt[:60]}…")

    if await _huggingface_generate(prompt, save_path):
        return True
    print("[IMAGE] HuggingFace failed — trying Gemini 2.5 Flash Image…")

    if await _gemini_generate(prompt, save_path):
        return True
    print("[IMAGE] Gemini failed — trying Imagen 4 Fast…")

    if await _imagen4_generate(prompt, save_path):
        return True
    print("[IMAGE] Imagen4 failed — trying Replicate…")

    if await _replicate_generate(prompt, save_path):
        return True
    print("[IMAGE] Replicate failed — trying Stability AI…")

    if await _stability_generate(prompt, save_path):
        return True
    print("[IMAGE] Stability failed — trying Pollinations.ai…")

    if await _pollinations_generate(prompt, save_path):
        return True

    print(f"[IMAGE] All providers failed for: {prompt[:60]}")
    return False


async def enrich_worksheet_with_images(worksheet: dict, output_dir: Path) -> dict:
    """
    For every question that carries an ``image_prompt`` field, generate an
    image and add ``image_path`` pointing to the saved file.
    """
    print(f"[IMAGE] enrich_worksheet_with_images called with output_dir: {output_dir}")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine the project root to create relative web paths
    project_root = Path(__file__).resolve().parent.parent
    
    image_questions = []
    for section in worksheet.get("sections", []):
        for q in section.get("questions", []):
            if q.get("image_prompt", "").strip():
                image_questions.append(q)
    
    if not image_questions:
        print("[IMAGE] No questions found that have an 'image_prompt'.")
        return worksheet

    print(f"[IMAGE] Processing {len(image_questions)} image prompts in parallel...")

    async def _process_one(idx, q):
        prompt = q["image_prompt"].strip()
        safe_num = q.get("number", f"unk{idx}")
        save_path = output_dir / f"q{safe_num}.png"
        
        # Stagger starts to avoid rate limits (3 seconds between each request)
        await asyncio.sleep(idx * 3.0)
        
        print(f"[IMAGE] Question {safe_num}: Generating image...")
        start_q = time.time()
        success = await generate_image(prompt, save_path)
        q_duration = time.time() - start_q
        
        if success:
            try:
                # Try to create relative path, fallback to absolute if it fails
                try:
                    rel_path = save_path.relative_to(project_root)
                    web_path = "/" + str(rel_path).replace("\\", "/")
                except ValueError:
                    # If save_path is not relative to project_root, use absolute path
                    web_path = "/" + str(save_path.name)
                
                q["image_path"] = web_path
                # Embed the image as base64 so the PDF renderer doesn't depend
                # on the server-side file being present at download time.
                with open(save_path, "rb") as fh:
                    q["image_data"] = base64.b64encode(fh.read()).decode("utf-8")
                print(f"[IMAGE] SUCCESS: Question {safe_num} took {q_duration:.2f}s")
            except Exception as ve:
                print(f"[IMAGE] Path error for Question {safe_num}: {ve}")
                # Still mark as failed but don't crash
        else:
            print(f"[IMAGE] FAILURE: Question {safe_num} failed after {q_duration:.2f}s")

    await asyncio.gather(*(_process_one(i, q) for i, q in enumerate(image_questions)))
    return worksheet
