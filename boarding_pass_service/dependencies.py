from typing import Annotated

from fastapi import Depends, Request
from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import async_sessionmaker

from boarding_pass_service.locations import LocationsClient

# Everything is still built once in AppState at startup; these only hand it to the handlers.
#
# Note what is injected: the session *factory*, never an open AsyncSession. The usual
# `async with session() as s: yield s` dependency checks a connection out of the pool before the
# handler body runs and holds it until the response is done - on the parse endpoint that would mean
# holding a connection through the pdf render (~370 ms) and the locations call, to do ~12 ms of
# actual work. Handing over the factory lets the DAO open the session at the moment of the query
# instead, so a connection is held only while it is used.


def get_settings(request: Request) -> BaseSettings:
    return request.app.state.settings


def get_session_master(request: Request) -> async_sessionmaker:
    """Writes go to the master."""
    return request.app.state.session_master


def get_session_slave(request: Request) -> async_sessionmaker:
    """Reads go to the slave."""
    return request.app.state.session_slave


def get_locations(request: Request) -> LocationsClient:
    return request.app.state.locations


AppSettings = Annotated[BaseSettings, Depends(get_settings)]
SessionMaster = Annotated[async_sessionmaker, Depends(get_session_master)]
SessionSlave = Annotated[async_sessionmaker, Depends(get_session_slave)]
Locations = Annotated[LocationsClient, Depends(get_locations)]
