import asyncio
import logging
import time
from typing import Dict, Iterable, Optional, Tuple

import httpx

from boarding_pass_service.schemas import Location

logger = logging.getLogger("boarding-pass-service.locations")


class LocationsClient:
    """Resolves IATA codes into airport/city/country names via the public locations API.

    Lookups are best effort. When the API is slow, down or does not know a code, the location is
    returned with only the ``code`` filled in, so that parsing a boarding pass never fails because
    of a third party outage.

    Alternatives, if fully enriched data mattered more than availability:
      * fail the parse request with a 502 here,
      * or store the codes only and backfill the names later from an async job / periodic worker
        (that also lets us keep a persistent airports table instead of this in-process cache).
        and can update if the airport name or any data changes over time.
    """

    def __init__(self, url: str, client: httpx.AsyncClient, cache_ttl_seconds: int = 86400):
        self.url = url
        self.client = client
        self.cache_ttl_seconds = cache_ttl_seconds
        # in-process cache only, a shared cache (redis) would be the production choice
        self._cache: Dict[str, Tuple[float, Location]] = {}

    async def resolve(self, codes: Iterable[str]) -> Dict[str, Location]:
        wanted = {code for code in codes if code}
        resolved: Dict[str, Location] = {}
        missing = []

        for code in wanted:
            cached = self._get_cached(code)
            if cached is not None:
                resolved[code] = cached
            else:
                missing.append(code)

        if missing:
            # all misses in parallel, one slow airport should not serialize the whole request
            results = await asyncio.gather(*(self._fetch(code) for code in missing), return_exceptions=True)
            for code, result in zip(missing, results):
                if isinstance(result, Exception) or result is None:
                    logger.warning("Could not resolve location %s: %s", code, result)
                    resolved[code] = Location(code=code)
                else:
                    self._cache[code] = (time.monotonic(), result)
                    resolved[code] = result

        return resolved

    def _get_cached(self, code: str) -> Optional[Location]:
        entry = self._cache.get(code)
        if entry is None:
            return None

        stored_at, location = entry
        if time.monotonic() - stored_at > self.cache_ttl_seconds:
            del self._cache[code]
            return None

        return location

    async def _fetch(self, code: str) -> Optional[Location]:
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
