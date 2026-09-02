from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gbif_user_agent: str = "MAPI/0.1 (species occurrence maps; research/education)"
    gbif_base_url: str = "https://api.gbif.org"
    inat_base_url: str = "https://api.inaturalist.org"
    iucn_base_url: str = "https://api.iucnredlist.org"
    iucn_api_token: str | None = None
    redis_url: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    gbif_username: str | None = None
    gbif_password: str | None = None
    gbif_download_email: str | None = None
    cors_origins: str = "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173"

    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
