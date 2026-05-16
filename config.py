"""
Configuration for NVIDIA VLM and other services
"""
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

class NVIDIAConfig:
    """NVIDIA API configuration"""
    vlm_key = os.getenv("NVIDIA_VLM_KEY", "")
    
class GeminiConfig:
    """Gemini API configuration"""
    api_key = os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

class Config:
    """Main configuration class"""
    nvidia = NVIDIAConfig()
    gemini = GeminiConfig()

config = Config()
