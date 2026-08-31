import httpx
import pytest

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


def make_client(handler) -> LocationsClient:
    return LocationsClient(API_URL, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


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


async def test_resolve_cache_expires():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["id"])
        return httpx.Response(200, json=PRG_RESPONSE)

    # ttl of zero, so the entry is already stale by the time it is looked up again
    client = LocationsClient(API_URL, httpx.AsyncClient(transport=httpx.MockTransport(handler)), cache_ttl_seconds=0)
    await client.resolve(["PRG"])
    await client.resolve(["PRG"])

    assert calls == ["PRG", "PRG"]
