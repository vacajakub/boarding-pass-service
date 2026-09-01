import asyncio
import logging
from typing import Dict, Iterable, List, Optional, Tuple

import httpx
from redis.asyncio import Redis

from boarding_pass_service.schemas import Location

logger = logging.getLogger("boarding-pass-service.locations")

CACHE_KEY_PREFIX = "loc:"


class LocationsClient:
    """Resolves IATA codes into airport/city/country names via the public locations API,
    caching the results in redis.

    Best effort: a failing API or cache yields a Location with only the ``code`` set, so an outage
    never fails the parse. If enriched data mattered more than availability we would either fail
    with a 502 here, or store codes only and backfill the names from a (cron)job - which would
    also pick up airports whose details change over time.
    """

    def __init__(self, url: str, client: httpx.AsyncClient, redis: Redis, cache_ttl_seconds: int = 86400):
        self.url = url
        self.client = client
        self.redis = redis
        self.cache_ttl_seconds = cache_ttl_seconds

    async def resolve(self, codes: Iterable[str]) -> Dict[str, Location]:
        wanted = sorted({code for code in codes if code})
        if not wanted:
            return {}

        resolved, cache_available = await self._get_cached(wanted)
        missing = [code for code in wanted if code not in resolved]

        if missing:
            # all misses in parallel, one slow airport should not serialize the whole request
            results = await asyncio.gather(*(self._fetch_from_api(code) for code in missing), return_exceptions=True)
            for code, result in zip(missing, results):
                if isinstance(result, Exception) or result is None:
                    logger.warning("Could not resolve location %s: %s", code, result)
                    resolved[code] = Location(code=code)
                else:
                    if cache_available:
                        await self._store(code, result)
                    resolved[code] = result

        return resolved

    async def _get_cached(self, codes: List[str]) -> Tuple[Dict[str, Location], bool]:
        """One MGET for the whole request rather than a round trip per code.

        Also reports whether the cache answered at all, so that a request which already found it
        unreachable does not stall again on the writes.
        """
        try:
            cached = await self.redis.mget([CACHE_KEY_PREFIX + code for code in codes])
        except Exception as e:
            # a cache we cannot read is a cache miss, never an error the caller has to handle
            logger.warning("Could not read locations from cache: %s", e)
            return {}, False

        return {code: Location.model_validate_json(raw) for code, raw in zip(codes, cached) if raw}, True

    async def _store(self, code: str, location: Location) -> None:
        if self.cache_ttl_seconds <= 0:
            return

        try:
            # redis expires the key after ttl
            await self.redis.set(CACHE_KEY_PREFIX + code, location.model_dump_json(), ex=self.cache_ttl_seconds)
        except Exception as e:
            logger.debug("Could not cache location %s: %s", code, e)

    async def _fetch_from_api(self, code: str) -> Optional[Location]:
        response = await self.client.get(self.url, params={"id": code})
        response.raise_for_status()

        locations = response.json().get("locations") or []
        if not locations:
            logger.info("Locations API does not know code %s", code)
            return None

        location = locations[0]
        city = location.get("city") or {}
        country = city.get("country") or {}

        return Location(
            code=code,
            airport_name=location.get("name"),
            city_name=city.get("name"),
            country=country.get("name"),
        )
