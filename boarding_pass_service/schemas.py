from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_serializer


class CabinClass(str, Enum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"
    UNKNOWN = "unknown"


class Location(BaseModel):
    code: str
    # nulls when the locations API is unreachable or does not know the code, see locations.py
    airport_name: Optional[str] = None
    city_name: Optional[str] = None
    country: Optional[str] = None


class Leg(BaseModel):
    booking_reference: Optional[str] = None
    airline_code: Optional[str] = None
    flight_number: Optional[str] = None
    julian_date: Optional[int] = None
    cabin_class: CabinClass = CabinClass.UNKNOWN
    seat: Optional[str] = None
    passenger_status: Optional[str] = None
    origin: Location
    destination: Location


class DecodedBcbp(BaseModel):
    passenger_name: Optional[str] = None
    legs: List[Leg] = []


class ParseBoardingPassResponse(BaseModel):
    decoded_bcbp: DecodedBcbp


class BoardingPassListItem(BaseModel):
    id: UUID
    parsed_at: datetime
    decoded_bcbp: DecodedBcbp

    @field_serializer("parsed_at")
    def serialize_parsed_at(self, value: datetime) -> str:
        # always UTC with a trailing Z, as in the API spec
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BoardingPassListResponse(BaseModel):
    items: List[BoardingPassListItem]
    total: int
    limit: int
    offset: int
