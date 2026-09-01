import httpx
import pytest
from fakeredis.aioredis import FakeRedis

from boarding_pass_service.locations import LocationsClient

API_URL = "https://api.skypicker.com/locations/id"

PRG_RESPONSE = {
    "locations": [
        {
            "code": "PRG",
            "name": "Václav Havel Airport Prague",
            "city": {"name": "Prague", "country": {"name": "Czechia", "code": "CZ"}},
        }
    ]
}


def make_client(handler, cache_ttl_seconds: int = 86400) -> LocationsClient:
    # fakeredis speaks the real redis API in process, so no container and no socket
    return LocationsClient(
        API_URL,
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        FakeRedis(decode_responses=True),
        cache_ttl_seconds,
    )


async def test_resolve_maps_response():
    locations = await make_client(lambda request: httpx.Response(200, json=PRG_RESPONSE)).resolve(["PRG"])

    assert locations["PRG"].code == "PRG"
    assert locations["PRG"].airport_name == "Václav Havel Airport Prague"
    assert locations["PRG"].city_name == "Prague"
    assert locations["PRG"].country == "Czechia"


async def test_resolve_caches():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["id"])
        return httpx.Response(200, json=PRG_RESPONSE)

    client = make_client(handler)
    await client.resolve(["PRG"])
    await client.resolve(["PRG", "PRG"])

    assert calls == ["PRG"]


async def test_resolve_deduplicates_codes():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["id"])
        return httpx.Response(200, json=PRG_RESPONSE)

    locations = await make_client(handler).resolve(["PRG", "PRG"])

    assert calls == ["PRG"]
    assert set(locations) == {"PRG"}


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(200, json={"locations": []}),
    ],
)
async def test_resolve_degrades_gracefully(handler):
    # a failing or unaware locations API must not break parsing, only the names are missing
    locations = await make_client(handler).resolve(["XXX"])

    assert locations["XXX"].code == "XXX"
    assert locations["XXX"].airport_name is None
    assert locations["XXX"].city_name is None
    assert locations["XXX"].country is None


async def test_resolve_survives_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    locations = await make_client(handler).resolve(["KSC"])

    assert locations["KSC"].code == "KSC"
    assert locations["KSC"].airport_name is None


async def test_resolve_ignores_empty_codes():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called")

    assert await make_client(handler).resolve([None, ""]) == {}


async def test_resolve_without_caching():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["id"])
        return httpx.Response(200, json=PRG_RESPONSE)

    # a ttl of zero disables caching outright, so every call goes to the API
    client = make_client(handler, cache_ttl_seconds=0)
    await client.resolve(["PRG"])
    await client.resolve(["PRG"])

    assert calls == ["PRG", "PRG"]


async def test_resolve_survives_an_unreachable_cache():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["id"])
        return httpx.Response(200, json=PRG_RESPONSE)

    class BrokenRedis:
        async def mget(self, *args, **kwargs):
            raise ConnectionError("redis is down")

        async def set(self, *args, **kwargs):
            raise ConnectionError("redis is down")

    client = LocationsClient(API_URL, httpx.AsyncClient(transport=httpx.MockTransport(handler)), BrokenRedis())

    # a cache we cannot reach degrades to no caching, it must never fail the lookup
    first = await client.resolve(["PRG"])
    second = await client.resolve(["PRG"])

    assert first["PRG"].airport_name == "Václav Havel Airport Prague"
    assert second["PRG"].airport_name == "Václav Havel Airport Prague"
    assert calls == ["PRG", "PRG"]
