import pytest

from app.cache import reset_cache_for_tests
from app.config import Settings, get_settings

LLM_ENV_VARS = (
    "LLM_PROVIDER",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_JSON_MODE",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
)


@pytest.fixture(autouse=True)
def _isolate_settings_and_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()
    get_settings.cache_clear()
