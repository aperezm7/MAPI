from dataclasses import dataclass
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str
    model: str
    key_fields: tuple[str, ...]
    json_mode: bool = True


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "openai": ProviderPreset("https://api.openai.com/v1", "gpt-4o-mini", ("openai_api_key",)),
    "groq": ProviderPreset("https://api.groq.com/openai/v1", "openai/gpt-oss-20b", ("groq_api_key",)),
    "gemini": ProviderPreset(
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-3.8-flash",
        ("gemini_api_key", "google_api_key"),
    ),
    "openrouter": ProviderPreset("https://openrouter.ai/api/v1", "openai/gpt-oss-20b", ("openrouter_api_key",)),
    "ollama": ProviderPreset("http://127.0.0.1:11434/v1", "gemma4", ()),
}

# Order used when LLM_PROVIDER is unset/"auto": first provider with a key wins.
AUTO_ORDER = ("openai", "gemini", "groq", "openrouter")
PROVIDER_ALIASES = {"google": "gemini", "custom": "openai_compatible", "compatible": "openai_compatible"}


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    base_url: str
    model: str
    api_key: str | None
    timeout: float
    json_mode: bool
    configured: bool
    problem: str | None = None

    @property
    def is_local(self) -> bool:
        return self.provider == "ollama"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    gbif_user_agent: str = "MAPI/0.1 (species occurrence maps; research/education)"
    gbif_base_url: str = "https://api.gbif.org"
    inat_base_url: str = "https://api.inaturalist.org"
    iucn_base_url: str = "https://api.iucnredlist.org"
    iucn_api_token: str | None = None
    redis_url: str | None = None

    llm_provider: str = "auto"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float | None = None
    llm_json_mode: bool | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    google_api_key: str | None = None
    openrouter_api_key: str | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None

    gbif_username: str | None = None
    gbif_password: str | None = None
    gbif_download_email: str | None = None
    cors_origins: str = "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173,http://localhost:5175,http://127.0.0.1:5175"

    auth_required: bool = False
    mapi_admin_token: str | None = None
    mapi_secret_key: str | None = None
    database_path: str = "data/mapi.sqlite"
    quota_maps_per_day: int = 100
    quota_plans_per_day: int = 40
    quota_requests_per_minute: int = 30
    default_budget: float = 100
    cost_map: float = 1
    cost_plan: float = 2
    cost_resolve: float = 0.1
    cost_download: float = 5
    cost_export: float = 1
    cost_inat: float = 0.2

    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def _key_for(self, provider: str) -> str | None:
        preset = PROVIDER_PRESETS.get(provider)
        for field in preset.key_fields if preset else ():
            value = (getattr(self, field) or "").strip()
            # "ollama" was the placeholder key in older configs; it is not a real credential.
            if value and value.lower() != "ollama":
                return value
        return None

    def _requested_provider(self) -> str:
        name = (self.llm_provider or "auto").strip().lower().replace("-", "_")
        name = PROVIDER_ALIASES.get(name, name)
        if name != "auto":
            return name
        if self.llm_base_url:
            return "openai_compatible"
        for candidate in AUTO_ORDER:
            if self._key_for(candidate):
                return candidate
        if self.llm_api_key:
            return "openai"
        return "ollama"

    def llm(self) -> LlmConfig:
        provider = self._requested_provider()
        if provider == "ollama":
            base_url = self.llm_base_url or self.ollama_base_url or self.openai_base_url or PROVIDER_PRESETS["ollama"].base_url
            model = self.llm_model or self.ollama_model or self.openai_model or PROVIDER_PRESETS["ollama"].model
            return LlmConfig(
                provider="ollama",
                base_url=base_url.rstrip("/"),
                model=model,
                api_key=self.llm_api_key or "ollama",
                timeout=self.llm_timeout_seconds or 180.0,
                json_mode=True if self.llm_json_mode is None else self.llm_json_mode,
                configured=True,
            )

        if provider == "openai_compatible":
            base_url = self.llm_base_url or self.openai_base_url
            model = self.llm_model or self.openai_model
            missing = [name for name, value in (("LLM_BASE_URL", base_url), ("LLM_MODEL", model)) if not value]
            return LlmConfig(
                provider=provider,
                base_url=(base_url or "").rstrip("/"),
                model=model or "",
                api_key=self.llm_api_key or self.openai_api_key,
                timeout=self.llm_timeout_seconds or 60.0,
                json_mode=True if self.llm_json_mode is None else self.llm_json_mode,
                configured=not missing,
                problem=f"Set {' and '.join(missing)} for LLM_PROVIDER=openai_compatible." if missing else None,
            )

        preset = PROVIDER_PRESETS.get(provider)
        if preset is None:
            known = ", ".join([*PROVIDER_PRESETS, "openai_compatible", "auto"])
            return LlmConfig(
                provider=provider,
                base_url="",
                model="",
                api_key=None,
                timeout=60.0,
                json_mode=False,
                configured=False,
                problem=f"Unknown LLM_PROVIDER '{provider}'. Use one of: {known}.",
            )

        legacy_base = self.openai_base_url if provider == "openai" else None
        legacy_model = self.openai_model if provider == "openai" else None
        api_key = self.llm_api_key or self._key_for(provider)
        key_names = " or ".join(field.upper() for field in preset.key_fields)
        return LlmConfig(
            provider=provider,
            base_url=(self.llm_base_url or legacy_base or preset.base_url).rstrip("/"),
            model=self.llm_model or legacy_model or preset.model,
            api_key=api_key,
            timeout=self.llm_timeout_seconds or 60.0,
            json_mode=preset.json_mode if self.llm_json_mode is None else self.llm_json_mode,
            configured=bool(api_key),
            problem=None if api_key else f"Set {key_names} (or LLM_API_KEY) to use {provider}.",
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
