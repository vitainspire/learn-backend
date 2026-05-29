"""
Configuration for NVIDIA VLM and other services
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class NVIDIAConfig:
    """NVIDIA API configuration"""
    vlm_key = os.getenv("NVIDIA_VLM_KEY", "")
    
class OpenRouterConfig:
    """OpenRouter API configuration"""
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    model = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")

class Config:
    """Main configuration class"""
    nvidia = NVIDIAConfig()
    openrouter = OpenRouterConfig()
    # Legacy alias kept for any code still referencing config.gemini
    gemini = OpenRouterConfig()

config = Config()
