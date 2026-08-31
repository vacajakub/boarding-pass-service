from os import environ

import pytest
from sqlalchemy import text
from starlette.testclient import TestClient

from boarding_pass_service.main import app
from boarding_pass_service.models import SCHEMA
from boarding_pass_service.schemas import Location

# locations resolved locally, so the suite does not depend on the availability of the public API
FAKE_LOCATIONS = {
    "KSC": Location(code="KSC", airport_name="Košice International", city_name="Košice", country="Slovakia"),
    "PRG": Location(code="PRG", airport_name="Václav Havel Airport Prague", city_name="Prague", country="Czechia"),
}


@pytest.fixture(scope="module")
def test_app():
    # need to run inside 'with' so startup and shutdown (lifespan) events register
    with TestClient(app) as client:

        async def fake_resolve(codes):
            return {code: FAKE_LOCATIONS.get(code, Location(code=code)) for code in codes if code}

        app.state.locations.resolve = fake_resolve
        yield client


@pytest.fixture
def api_url():
    return environ.get("TEST_API_URL")


@pytest.fixture(autouse=True)
def clean_db(test_app):
    """Keep the tests independent of each other and of whatever is already in the db."""

    async def truncate():
        async with app.state.session_master() as session:
            await session.execute(text(f"TRUNCATE {SCHEMA}.boarding_passes, {SCHEMA}.boarding_pass_legs"))
            await session.commit()

    test_app.portal.call(truncate)
    yield
