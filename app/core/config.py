from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LabInventory"
    environment: str = "development"
    api_version: Literal["v1"] = "v1"
    protocol_version: Literal[1] = 1
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    cors_origins: str = ""

    postgres_db: str = "labinventory"
    postgres_user: str = "labinventory"
    postgres_password: SecretStr = SecretStr("labinventory_dev_password")
    postgres_host: str = "db"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    database_url: str | None = None

    upload_root: Path = Path("/data/uploads")
    instance_data_root: Path = Path("/data/instance")

    mdns_enabled: bool = False
    mdns_service_name: str = "LabInventory Backend"
    mdns_service_type: str = "_labinventory._tcp."
    mdns_advertise_ip: str | None = None
    mdns_fail_fast: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            msg = "LOG_LEVEL must not be empty."
            raise ValueError(msg)
        return normalized

    @field_validator("protocol_version", mode="before")
    @classmethod
    def coerce_protocol_version(cls, value: object) -> object:
        if value == "1":
            return 1
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if any(origin == "*" for origin in origins):
            msg = "CORS_ORIGINS must not contain wildcard origins."
            raise ValueError(msg)
        return ",".join(origins)

    @field_validator("database_url", "mdns_advertise_ip", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("mdns_service_name")
    @classmethod
    def validate_mdns_service_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "MDNS_SERVICE_NAME must not be empty."
            raise ValueError(msg)
        return normalized

    @field_validator("mdns_service_type")
    @classmethod
    def validate_mdns_service_type(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != "_labinventory._tcp.":
            msg = "MDNS_SERVICE_TYPE must be _labinventory._tcp. for Phase 0."
            raise ValueError(msg)
        return normalized

    @field_validator("upload_root", "instance_data_root")
    @classmethod
    def validate_path(cls, value: Path) -> Path:
        if str(value).strip() in {"", "."}:
            msg = "Filesystem root settings must not be empty or the current directory."
            raise ValueError(msg)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        if not self.cors_origins:
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password.get_secret_value())
        host = self.postgres_host
        port = self.postgres_port
        db_name = quote_plus(self.postgres_db)
        return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db_name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
