"""
Image generation for worksheet questions.

Generation strategy (tried in order):
  1. Gemini image model  — used if the API key has access (paid tier).
  2. Pollinations.ai     — free, no API key, always available as fallback.

The caller (enrich_worksheet_with_images) never raises — every failure is
logged and skipped so the worksheet is always returned intact.
"""

import os
import base64
import hashlib
import time
import asyncio
import urllib.parse
import httpx
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
_G_MODEL  = "gemini-2.0-flash-exp-image-generation"
_G_BASE   = "https://generativelanguage.googleapis.com/v1beta/models"

# Cartoon style suffix appended to every prompt for consistent aesthetics
_STYLE = (
    "cartoon style, flat illustration, child-friendly educational art, "
    "bright colours, white background, no text, no words, no letters"
)

# Probe cache: None = not yet checked
_gemini_available: bool | None = None


# ── Gemini ────────────────────────────────────────────────────────────────────

async def _gemini_probe() -> bool:
    global _gemini_available
    if _gemini_available is not None:
        return _gemini_available
    url = f"{_G_BASE}/{_G_MODEL}:generateContent?key={_API_KEY}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json={
                "contents": [{"parts": [{"text": "red apple"}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            }, timeout=15)
            _gemini_available = r.status_code not in (404, 403)
    except Exception:
        _gemini_available = False
    if _gemini_available:
        print("[IMAGE] Gemini image model available — will use for high-quality generation.")
    else:
        print("[IMAGE] Gemini image model unavailable — using Pollinations.ai fallback.")
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
                return False
            for part in (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", []):
                if "inlineData" in part:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(base64.b64decode(part["inlineData"]["data"]))
                    return True
        return False
    except Exception:
        return False


# ── Pollinations.ai ───────────────────────────────────────────────────────────

async def _pollinations_generate(prompt: str, save_path: Path, retries: int = 3) -> bool:
    """
    Pollinations.ai — completely free, no API key, powered by Flux.
    """
    full_prompt = f"{prompt}, {_STYLE}"
    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % 100_000
    encoded = urllib.parse.quote(full_prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?model=flux&width=512&height=384&nologo=true&seed={seed}"
    )

    async with httpx.AsyncClient() as client:
        for attempt in range(1, retries + 1):
            try:
                r = await client.get(url, timeout=45)
                if r.status_code != 200:
                    print(f"[IMAGE] Pollinations HTTP {r.status_code} (attempt {attempt}/{retries})")
                    await asyncio.sleep(2 * attempt)
                    continue
                # Reject HTML error pages
                if r.content[:5].lower().lstrip() == b"<html" or b"<html" in r.content[:120].lower():
                    print(f"[IMAGE] Pollinations returned HTML (attempt {attempt}/{retries})")
                    await asyncio.sleep(2 * attempt)
                    continue
                if len(r.content) < 1000:
                    print(f"[IMAGE] Pollinations response too small ({len(r.content)} B) — retrying")
                    await asyncio.sleep(2 * attempt)
                    continue
                save_path.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(r.content)
                print(f"[IMAGE] Generated via Pollinations: {save_path.name} (attempt {attempt})")
                return True
            except Exception as e:
                print(f"[IMAGE] Pollinations attempt {attempt}/{retries} failed: {e}")
                await asyncio.sleep(2 * attempt)

    print(f"[IMAGE] Pollinations gave up after {retries} attempts for: {prompt[:60]}")
    return False


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_image(prompt: str, save_path: Path) -> bool:
    """
    Use Pollinations.ai only (Gemini image generation commented out).
    Returns True if an image was saved at save_path, False otherwise.
    """
    print(f"[IMAGE] Attempting generation for prompt: {prompt[:50]}...")
    
    # COMMENTED OUT: Gemini image generation disabled, using only Pollinations AI
    # if await _gemini_generate(prompt, save_path):
    #     print(f"[IMAGE] SUCCESS: Gemini generated {save_path.name}")
    #     return True
    
    print(f"[IMAGE] Using Pollinations.ai for image generation...")
    if await _pollinations_generate(prompt, save_path):
        print(f"[IMAGE] SUCCESS: Pollinations generated {save_path.name}")
        return True
        
    print(f"[IMAGE] CRITICAL: Pollinations.ai failed for: {prompt[:50]}")
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
        
        # Stagger starts slightly to avoid hitting rate limits simultaneously
        await asyncio.sleep(idx * 0.5)
        
        print(f"[IMAGE] Question {safe_num}: Generating image...")
        start_q = time.time()
        success = await generate_image(prompt, save_path)
        q_duration = time.time() - start_q
        
        if success:
            try:
                rel_path = save_path.relative_to(project_root)
                web_path = "/" + str(rel_path).replace("\\", "/")
                q["image_path"] = web_path
                # Embed the image as base64 so the PDF renderer doesn't depend
                # on the server-side file being present at download time.
                with open(save_path, "rb") as fh:
                    q["image_data"] = base64.b64encode(fh.read()).decode("utf-8")
                print(f"[IMAGE] SUCCESS: Question {safe_num} took {q_duration:.2f}s")
            except Exception as ve:
                print(f"[IMAGE] Path warning/error for Question {safe_num}: {ve}")
                q["image_path"] = str(save_path)
        else:
            print(f"[IMAGE] FAILURE: Question {safe_num} failed after {q_duration:.2f}s")

    await asyncio.gather(*(_process_one(i, q) for i, q in enumerate(image_questions)))
    return worksheet
