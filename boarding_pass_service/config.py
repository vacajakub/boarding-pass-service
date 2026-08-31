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

    # public locations API used to resolve IATA codes into airport/city/country names
    locations_api_url: str = "https://api.skypicker.com/locations/id"
    locations_api_timeout: float = 3.0
    locations_cache_ttl_seconds: int = 86400

    # uploads - keep a hard cap so a huge file cannot eat all the memory of the worker
    max_upload_size_bytes: int = 10 * 1024 * 1024
    # scale of the page render handed to the barcode reader, 1.0 == 72 DPI
    pdf_render_scale: float = 3.0
    # second, more expensive attempt for pages where nothing was decoded on the first pass
    pdf_render_scale_retry: float = 5.0


@lru_cache()
def get_settings() -> BaseSettings:
    return Settings()
