"""
Supabase client — replaces the old SQLAlchemy engine.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_env_file)
except ImportError:
    pass

from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set in your .env file.")

_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_db() -> Client:
    """FastAPI dependency — returns the shared Supabase client."""
    return _client
