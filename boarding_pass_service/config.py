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

    # Connection budget, per engine. There are two engines (master, slave) in every worker, so the
    # ceiling is workers * 2 * (db_pool_size + db_max_overflow) and it has to stay under the
    # max_connections of the server, minus what is reserved for superusers and for the odd psql
    # session. With the 8 workers from conf/gunicorn.conf.py and postgres defaulting to 100:
    #     8 * 2 * (3 + 2) = 80
    # Raise these together with max_connections, or put a pgbouncer in front and raise them a lot.
    db_pool_size: int = 3
    db_max_overflow: int = 2
    # fail fast instead of piling up requests waiting for a connection that is not coming
    db_pool_timeout: float = 10.0
    # recycle connections before a proxy or the server drops them from under us
    db_pool_recycle: int = 1800

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
