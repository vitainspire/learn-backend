# Image Generation Setup Guide

## Overview

The worksheet image generation system uses a multi-provider fallback strategy to ensure reliability. When one provider fails or runs out of credits, it automatically tries the next one.

## Provider Priority (in order)

1. **Hugging Face** (Primary) - Fast, free tier available
2. **Gemini** - Google's image generation
3. **Replicate** - 50 free predictions/month
4. **Stability AI** - 25 free credits/month  
5. **Pollinations.ai** - No API key required (last resort)

## Setup Instructions

### 1. Hugging Face (Recommended Primary)

1. Create account at https://huggingface.co/
2. Go to Settings → Access Tokens
3. Create a new token with "Read" permissions
4. Add to `.env`:
   ```
   HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxx
   ```

**Free Tier:** Limited monthly credits (resets monthly)

### 2. Replicate (Recommended Fallback)

1. Create account at https://replicate.com/
2. Go to Account → API Tokens
3. Create a new token
4. Add to `.env`:
   ```
   REPLICATE_API_TOKEN=r8_xxxxxxxxxxxxxxxxxxxxx
   ```

**Free Tier:** 50 predictions per month

### 3. Stability AI (Additional Fallback)

1. Create account at https://platform.stability.ai/
2. Go to Account → API Keys
3. Create a new API key
4. Add to `.env`:
   ```
   STABILITY_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx
   ```

**Free Tier:** 25 credits per month (~25 images)

### 4. Gemini (Optional)

Already configured if you have `GEMINI_API_KEY` set for other features.

### 5. Pollinations.ai

No setup required - works without API key as last resort fallback.

## Current Issue Resolution

Your error logs show:
- **HuggingFace**: 402 Payment Required (monthly credits depleted)
- **Gemini**: Unavailable (check if API key is set)
- **Pollinations**: 429 Rate Limit (too many requests)

### Immediate Solutions:

**Option A: Add More Providers** (Recommended)
1. Sign up for Replicate (50 free/month)
2. Sign up for Stability AI (25 free/month)
3. Add tokens to `.env` file
4. Restart your application

**Option B: Wait for Reset**
- HuggingFace credits reset monthly
- Pollinations rate limits reset after cooldown period

**Option C: Reduce Parallel Load**
The updated code now:
- Staggers requests by 3 seconds instead of 1 second
- Adds rate limiting between provider calls
- Skips retries on 402 errors (saves time)

## Testing

Test image generation with:

```python
from services.image_service import generate_image
from pathlib import Path
import asyncio

async def test():
    success = await generate_image(
        "a red apple on a table",
        Path("test_output/test.png")
    )
    print(f"Success: {success}")

asyncio.run(test())
```

## Monitoring

Watch the logs for provider status:
- `[IMAGE] HuggingFace OK` - Success
- `[IMAGE] HuggingFace failed — trying Gemini…` - Fallback triggered
- `[IMAGE] All providers failed` - All providers exhausted

## Cost Management

To minimize costs and stay within free tiers:

1. **Distribute load across providers** - Set up multiple providers
2. **Reduce parallel requests** - Already implemented (3s stagger)
3. **Cache generated images** - Reuse images when possible
4. **Monitor usage** - Check provider dashboards regularly

## Troubleshooting

### All providers failing?
1. Check `.env` file has correct API keys
2. Verify API keys are active in provider dashboards
3. Check if you've exceeded free tier limits
4. Try running one image at a time to isolate issues

### Rate limit errors (429)?
- Increase stagger time in `image_service.py` (currently 3s)
- Reduce number of parallel image generations
- Wait a few minutes before retrying

### 402 Payment Required?
- Free tier credits depleted
- Either wait for monthly reset or add payment method
- Switch to alternative providers

## Recommended Configuration

For best reliability with free tiers:

```env
# Primary
HF_TOKEN=your-huggingface-token

# Fallbacks
REPLICATE_API_TOKEN=your-replicate-token
STABILITY_API_KEY=your-stability-key

# Optional
GEMINI_API_KEY=your-gemini-key
```

This gives you:
- HuggingFace monthly credits
- 50 Replicate predictions/month
- 25 Stability images/month
- Unlimited Pollinations (with rate limits)

**Total free tier: ~100+ images/month** across all providers.
