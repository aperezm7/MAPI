from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    gbif_user_agent: str = "MAPI/0.1 (species occurrence maps; research/education)"
    gbif_base_url: str = "https://api.gbif.org"
    inat_base_url: str = "https://api.inaturalist.org"
    iucn_base_url: str = "https://api.iucnredlist.org"
    iucn_api_token: str | None = None
    redis_url: str | None = None
    llm_provider: str = "ollama"
    openai_api_key: str | None = None
    openai_base_url: str = "http://127.0.0.1:11434/v1"
    openai_model: str = "gemma4"
    gbif_username: str | None = None
    gbif_password: str | None = None
    gbif_download_email: str | None = None
    cors_origins: str = "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173,http://localhost:5175,http://127.0.0.1:5175"

    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def provider(self) -> str:
        return (self.llm_provider or "ollama").strip().lower()

    def llm_available(self) -> bool:
        if self.provider() == "ollama":
            return True
        return bool(self.openai_api_key)

    def llm_api_key(self) -> str:
        if self.openai_api_key:
            return self.openai_api_key
        if self.provider() == "ollama":
            return "ollama"
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
