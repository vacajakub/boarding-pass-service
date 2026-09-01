"""The failure branches of the handlers, driven by swapping in broken collaborators."""

import pytest
from sqlalchemy.exc import OperationalError

from tests.data import SAMPLE_PDF_PATH

from boarding_pass_service.config import Settings
from boarding_pass_service.dependencies import get_session_master, get_session_slave, get_settings
from boarding_pass_service.main import app


class BrokenSessionFactory:
    """Stands in for a database that is not reachable."""

    def __call__(self):
        raise OperationalError("connect failed", None, Exception("no route to host"))


@pytest.fixture
def override():
    added = []

    def _override(dependency, replacement):
        app.dependency_overrides[dependency] = replacement
        added.append(dependency)

    yield _override

    for dependency in added:
        del app.dependency_overrides[dependency]


def post_sample(test_app):
    with SAMPLE_PDF_PATH.open("rb") as file:
        return test_app.post(
            "/boarding-pass/parse-from-file",
            files={"file": ("boarding_pass.pdf", file, "application/pdf")},
        )


def test_upload_over_the_size_limit(test_app, override):
    small = Settings(**{**app.state.settings.model_dump(), "max_upload_size_bytes": 1024})
    override(get_settings, lambda: small)

    response = post_sample(test_app)

    assert response.status_code == 413
    assert "1024" in response.json()["detail"]


def test_readiness_reports_not_ready_when_the_db_is_down(test_app, override):
    override(get_session_slave, BrokenSessionFactory)

    response = test_app.get("/readiness")

    assert response.status_code == 412
    assert response.json()["detail"] == "Not Ready"


def test_liveness_does_not_depend_on_the_db(test_app, override):
    # liveness must stay up even when the database is gone, otherwise k8s restarts a healthy pod
    override(get_session_slave, BrokenSessionFactory)

    assert test_app.get("/liveness").status_code == 200


def test_parse_returns_500_when_storing_fails(test_app, override):
    override(get_session_master, BrokenSessionFactory)

    response = post_sample(test_app)

    # the pass parsed fine, it is the write that failed
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to store boarding pass"


def test_parse_returns_422_when_the_barcode_is_not_bcbp(test_app, monkeypatch):
    # a readable PDF417 that simply does not carry boarding pass data
    monkeypatch.setattr(
        "boarding_pass_service.routers.boarding_pass.extract_payloads",
        lambda *args, **kwargs: "M9" + "x" * 300,
    )

    response = post_sample(test_app)

    assert response.status_code == 422
    assert response.json()["detail"] == "Barcode does not contain valid BCBP data"


def test_parse_returns_500_on_an_unexpected_parsing_error(test_app, monkeypatch):
    def boom(*args, **kwargs):
        raise MemoryError("pdfium ran out of memory")

    monkeypatch.setattr("boarding_pass_service.routers.boarding_pass.extract_payloads", boom)

    response = post_sample(test_app)

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to parse boarding pass"
