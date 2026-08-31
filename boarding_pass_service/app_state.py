import logging

import httpx
from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from starlette.datastructures import State

from boarding_pass_service.config import get_settings
from boarding_pass_service.locations import LocationsClient
from boarding_pass_service.models import SCHEMA

logger = logging.getLogger("boarding-pass-service.app_state")


def get_db_url(settings: BaseSettings, read_only: bool = False) -> str:
    # asyncpg driver, so that no db call ever blocks the event loop
    return (
        f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_slave_port if read_only else settings.db_master_port}"
        f"/{settings.db_slave_name if read_only else settings.db_master_name}"
    )


def create_db_engine(settings: BaseSettings, read_only: bool = False) -> AsyncEngine:
    return create_async_engine(
        get_db_url(settings, read_only),
        echo=settings.db_echo,
        pool_pre_ping=True,
        # sized deliberately to avoid exhausting the db connection limit with many concurrent requests
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        connect_args={"server_settings": {"application_name": settings.db_app_name, "search_path": SCHEMA}},
    )


class AppState(State):
    settings: BaseSettings

    db_master: AsyncEngine
    db_slave: AsyncEngine
    session_master: async_sessionmaker
    session_slave: async_sessionmaker

    http_client: httpx.AsyncClient
    locations: LocationsClient

    async def setup(self):
        self.settings = get_settings()

        # on local docker-compose master and slave is same but in production environment it should not be
        # so reads on slave, writes and everything else on master
        self.db_master = create_db_engine(self.settings)
        self.db_slave = create_db_engine(self.settings, True)
        self.session_master = async_sessionmaker(self.db_master, expire_on_commit=False)
        self.session_slave = async_sessionmaker(self.db_slave, expire_on_commit=False)
        logger.info("DB engines created")

        # one shared client, so connections to the locations API are pooled and kept alive
        self.http_client = httpx.AsyncClient(timeout=self.settings.locations_api_timeout)
        self.locations = LocationsClient(
            self.settings.locations_api_url, self.http_client, self.settings.locations_cache_ttl_seconds
        )

        # here we could set up logging levels, etc.

    async def teardown(self):
        await self.http_client.aclose()
        await self.db_master.dispose()
        await self.db_slave.dispose()
