"""
Configuration — all AI calls now go through OpenRouter.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class OpenRouterConfig:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    model_fast      = os.getenv("OPENROUTER_MODEL_FAST",      "deepseek/deepseek-v4-flash:free")
    model_quality   = os.getenv("OPENROUTER_MODEL_QUALITY",   "nvidia/nemotron-3-super-120b-a12b:free")
    model_reasoning = os.getenv("OPENROUTER_MODEL_REASONING", "nvidia/nemotron-3-super-120b-a12b:free")
    model_vision    = os.getenv("OPENROUTER_MODEL_VISION",    "moonshotai/kimi-k2.6:free")


class Config:
    openrouter = OpenRouterConfig()


config = Config()
