"""Settings loaded from .env (see .env.example). Key values are never logged."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    meta_api_key: SecretStr | None = None
    meta_api_base_url: str = "https://api.meta.ai/v1"
    meta_spark_model: str = "muse-spark-1.3"

    baseten_api_key: SecretStr | None = None
    baseten_base_url: str = "https://inference.baseten.co/v1"
    baseten_model: str = "meta-models/muse-spark-open"

    actcheck_cache_dir: str = "data/cache"
    actcheck_output_dir: str = "outputs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
