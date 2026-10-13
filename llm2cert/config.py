"""Read provider settings and credentials from environment variables."""
import os
PROVIDER = os.getenv("DYNACERT_PROVIDER", "gpt").strip().lower()
JSON_OBJECT_MODE = os.getenv("DYNACERT_JSON_OBJECT_MODE", "0") == "1"
STRUCTURED_OUTPUTS = os.getenv("DYNACERT_STRUCTURED_OUTPUTS", "0") == "1"
DEFAULT_MODELS = {"openrouter":"openai/gpt-5.6-sol", "gpt":"openai/gpt-5.6-sol", "deepseek":"deepseek-v4-flash", "claude":"claude-opus-4-8"}
DEFAULT_URLS = {"openrouter":"https://openrouter.ai/api/v1", "gpt":"https://openrouter.ai/api/v1", "deepseek":"https://api.deepseek.com", "claude":""}
API_KEY = os.getenv("DYNACERT_API_KEY") or os.getenv("BARRIER_API_KEY") or ""
MODEL = os.getenv("DYNACERT_MODEL", DEFAULT_MODELS.get(PROVIDER, "gpt-5.6-sol"))
BASE_URL = os.getenv("DYNACERT_BASE_URL", DEFAULT_URLS.get(PROVIDER, ""))
