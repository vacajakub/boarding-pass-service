from datetime import datetime, timedelta, timezone
from uuid import uuid4

from boarding_pass_service.schemas import BoardingPassListItem, DecodedBcbp


def item(parsed_at: datetime) -> dict:
    return BoardingPassListItem(id=uuid4(), parsed_at=parsed_at, decoded_bcbp=DecodedBcbp()).model_dump(mode="json")


def test_parsed_at_is_serialized_as_utc_with_a_z():
    assert item(datetime(2026, 8, 10, 9, 14, 22, tzinfo=timezone.utc))["parsed_at"] == "2026-08-10T09:14:22Z"


def test_parsed_at_converts_other_offsets_to_utc():
    prague = timezone(timedelta(hours=2))
    assert item(datetime(2026, 8, 10, 11, 14, 22, tzinfo=prague))["parsed_at"] == "2026-08-10T09:14:22Z"


def test_parsed_at_assumes_utc_when_naive():
    # asyncpg can hand back a naive datetime, it must not silently shift by the local offset
    assert item(datetime(2026, 8, 10, 9, 14, 22))["parsed_at"] == "2026-08-10T09:14:22Z"
