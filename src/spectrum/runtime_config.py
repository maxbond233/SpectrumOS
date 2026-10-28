from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPECTRUM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://spectrum:spectrum@127.0.0.1:55432/spectrum"
    redis_url: str = "redis://127.0.0.1:56379/0"
    api_token: SecretStr = SecretStr("")
    host: str = "127.0.0.1"
    port: int = 8078
    s3_endpoint: str = "http://127.0.0.1:59000"
    s3_access_key: str = "spectrum"
    s3_secret_key: SecretStr = SecretStr("spectrum-local-storage")
    s3_bucket: str = "spectrum"
    model: str = "claude-sonnet-4-5-20250929"
    model_key_env: str = "CLAUDE_API_KEY"
    model_base_url_env: str = "CLAUDE_BASE_URL"
    model_timeout: int = 180
    input_price_per_million: float = Field(default=3.0, ge=0)
    output_price_per_million: float = Field(default=15.0, ge=0)
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dimensions: int = 512
    model_cache: Path = Path(".work/models")
    otlp_endpoint: str = ""
    langfuse_enabled: bool = False
    execution_timeout: int = 1800

    @property
    def postgres_dsn(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def runtime_settings() -> RuntimeSettings:
    load_dotenv(override=False)
    return RuntimeSettings()
