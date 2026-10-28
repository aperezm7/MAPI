import pytest
from fastapi.testclient import TestClient

from app.cache import reset_cache_for_tests
from app.config import Settings, get_settings
from app.main import create_app

ACCOUNT_ENV_VARS = (
    "AUTH_REQUIRED",
    "MAPI_ADMIN_TOKEN",
    "MAPI_SECRET_KEY",
    "DATABASE_PATH",
    "GBIF_USERNAME",
    "GBIF_PASSWORD",
    "GBIF_DOWNLOAD_EMAIL",
)

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
def _isolate_settings_and_cache(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from app.db import reset_db_for_tests
    from app.usage import reset_usage_for_tests

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in LLM_ENV_VARS + ACCOUNT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mapi.sqlite"))
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    reset_db_for_tests()
    reset_usage_for_tests()
    reset_cache_for_tests()
    # Drop the Settings object opened while preparing the database so a test can
    # still change env vars before the first request.
    get_settings.cache_clear()
    yield
    reset_cache_for_tests()
    reset_usage_for_tests()
    reset_db_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def client():
    get_settings.cache_clear()
    reset_cache_for_tests()
    with TestClient(create_app()) as test_client:
        yield test_client
    reset_cache_for_tests()
    get_settings.cache_clear()
