"""Suite-wide guard: no test may talk to anything outside this machine.

The parse path calls a public locations API, and a test that reached it for real would go red
whenever that API is slow, down or firewalled off the build agent. Locations are mocked everywhere;
this makes that structural rather than a convention. Only the database is let through.
"""

import os
import socket

import pytest

_real_getaddrinfo = socket.getaddrinfo


def _allowed_hosts() -> set:
    allowed = {"localhost", "127.0.0.1", "::1", "testserver", "0.0.0.0"}

    # whatever the database happens to be called in this environment - localhost when run against
    # the compose stack, "db" inside test-docker-compose
    for host in (os.environ.get("DB_HOST"), _settings_db_host(), _settings_redis_host()):
        if host:
            allowed.add(host)

    return allowed


def _settings_redis_host():
    try:
        from urllib.parse import urlparse

        from boarding_pass_service.config import get_settings

        return urlparse(get_settings().redis_url).hostname
    except Exception:  # pragma: no cover - only when the settings cannot be built at all
        return None


def _settings_db_host():
    try:
        from boarding_pass_service.config import get_settings

        return get_settings().db_host
    except Exception:  # pragma: no cover - only when the settings cannot be built at all
        return None


@pytest.fixture(autouse=True, scope="session")
def block_outbound_network():
    allowed = _allowed_hosts()

    def guard(host, port, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else host
        if name is not None and name not in allowed:
            raise RuntimeError(
                f"the test suite tried to reach {name}:{port}. Tests must not depend on anything "
                f"outside this machine - mock the response instead (see tests/conftest.py)."
            )
        return _real_getaddrinfo(host, port, *args, **kwargs)

    socket.getaddrinfo = guard
    yield
    socket.getaddrinfo = _real_getaddrinfo
