import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

CONF_FILE = os.environ.get("CONFFILE", "/app/conf/boarding-pass-service.env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=CONF_FILE, env_file_encoding="utf-8")

    db_host: str
    db_password: str
    db_master_name: str
    db_slave_name: str
    db_user: str
    db_master_port: int
    db_slave_port: int
    db_app_name: str = "boarding_pass"
    db_echo: bool = False

    log_level: str = "INFO"

    # Pooling config, we have multiple workers but currently no pgbouncer in front so be careful not to exhaust the connection budget
    db_pool_size: int = 3
    db_max_overflow: int = 2
    # fail fast instead of piling up requests waiting for a connection that is not coming
    db_pool_timeout: float = 10.0
    # recycle connections before a proxy or the server drops them from under us
    db_pool_recycle: int = 1800

    # shared cache for resolved airport names, so the workers do not each warm their own
    redis_url: str = "redis://redis:6379/0"
    # a cache that does not answer quickly is worse than no cache, the lookup falls back to the API
    redis_timeout: float = 1.0

    # public locations API used to resolve IATA codes into airport/city/country names
    locations_api_url: str = "https://api.skypicker.com/locations/id"
    locations_api_timeout: float = 3.0
    locations_cache_ttl_seconds: int = 86400

    # uploads - keep a hard cap so a huge file cannot eat all the memory of the worker
    max_upload_size_bytes: int = 100 * 1024 * 1024
    # scale of the page render handed to the barcode reader, 1.0 == 72 DPI
    pdf_render_scale: float = 3.0
    # second, more expensive attempt for pages where nothing was decoded on the first pass
    pdf_render_scale_retry: float = 5.0


@lru_cache()
def get_settings() -> BaseSettings:
    return Settings()
