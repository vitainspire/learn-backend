"""
Lists all models available to this API key, then attempts image generation
with any that support it.
"""
import os, base64, requests
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY", "")
PROMPT  = "A red apple on a wooden table, photorealistic"
BASE    = "https://generativelanguage.googleapis.com/v1beta"


def list_models():
    r = requests.get(f"{BASE}/models?key={API_KEY}", timeout=15)
    r.raise_for_status()
    models = r.json().get("models", [])
    return models


def try_generate(model_name: str):
    """Try generateContent with IMAGE modality on a given model."""
    url = f"{BASE}/{model_name}:generateContent?key={API_KEY}"
    body = {
        "contents": [{"parts": [{"text": PROMPT}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    r = requests.post(url, json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    for part in r.json()["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            out = f"test_output_{model_name.split('/')[-1]}.png"
            with open(out, "wb") as f:
                f.write(base64.b64decode(part["inlineData"]["data"]))
            print(f"  Saved to {out}")
            return True
    raise RuntimeError("Response had no image part")


def try_predict(model_name: str):
    """Try predict endpoint (Imagen-style)."""
    url = f"{BASE}/{model_name}:predict?key={API_KEY}"
    body = {
        "instances": [{"prompt": PROMPT}],
        "parameters": {"sampleCount": 1},
    }
    r = requests.post(url, json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    b64 = r.json()["predictions"][0]["bytesBase64Encoded"]
    out = f"test_output_{model_name.split('/')[-1]}.png"
    with open(out, "wb") as f:
        f.write(base64.b64decode(b64))
    print(f"  Saved to {out}")
    return True


if __name__ == "__main__":
    print("=== Models available to your key ===")
    models = list_models()
    image_candidates = []
    for m in models:
        name        = m.get("name", "")
        display     = m.get("displayName", name)
        methods     = m.get("supportedGenerationMethods", [])
        is_image    = any(k in name.lower() for k in ("imagen", "image"))
        print(f"  {display:45s}  methods: {methods}")
        if is_image:
            image_candidates.append((name, methods))

    print()
    if not image_candidates:
        print("No image-generation models found in your key's model list.")
        print("This key does not have access to Imagen or image-gen Gemini models.")
        print()
        print("Options:")
        print("  1. Enable billing in Google AI Studio and upgrade your plan.")
        print("  2. Use Vertex AI (Imagen on GCP) — requires GCP_PROJECT + auth.")
        print("  3. Use a third-party API (Stability AI, OpenAI DALL-E, etc.).")
    else:
        print("=== Attempting image generation ===")
        for name, methods in image_candidates:
            print(f"Trying {name} ...")
            try:
                fn = try_predict if "predict" in methods else try_generate
                if fn(name):
                    print("Done!")
                    break
            except Exception as e:
                print(f"  Failed: {e}")
