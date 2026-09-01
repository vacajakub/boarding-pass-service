from typing import Annotated

from fastapi import Depends, Request
from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import async_sessionmaker

from boarding_pass_service.locations import LocationsClient

# Everything is built once in AppState at startup; these only hand it to the handlers, which also
# makes it overridable in tests.
#
# The session *factory* is injected, never an open AsyncSession: the usual
# `async with session() as s: yield s` dependency would hold a pooled connection for the whole
# request, and on the parse endpoint that is ~370 ms of rendering to do a ~12 ms insert.


def get_settings(request: Request) -> BaseSettings:
    return request.app.state.settings


def get_session_master(request: Request) -> async_sessionmaker:
    return request.app.state.session_master


def get_session_slave(request: Request) -> async_sessionmaker:
    return request.app.state.session_slave


def get_locations(request: Request) -> LocationsClient:
    return request.app.state.locations


AppSettings = Annotated[BaseSettings, Depends(get_settings)]
SessionMaster = Annotated[async_sessionmaker, Depends(get_session_master)]
SessionSlave = Annotated[async_sessionmaker, Depends(get_session_slave)]
Locations = Annotated[LocationsClient, Depends(get_locations)]
