import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BoardingPass(Base):
    __tablename__ = "boarding_passes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    parsed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    passenger_name: Mapped[Optional[str]] = mapped_column(String(64))
    # the raw BCBP payload is kept so a pass can be re-decoded if the mapping ever changes
    raw_barcode: Mapped[str] = mapped_column(String, nullable=False)

    legs: Mapped[List["BoardingPassLeg"]] = relationship(
        back_populates="boarding_pass",
        order_by="BoardingPassLeg.leg_index",
        cascade="all, delete-orphan",
        # selectin, otherwise every serialization of a listing would trigger lazy IO in async context
        lazy="selectin",
    )


class BoardingPassLeg(Base):
    __tablename__ = "boarding_pass_legs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    boarding_pass_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boarding_passes.id", ondelete="CASCADE"), nullable=False
    )
    leg_index: Mapped[int] = mapped_column(Integer, nullable=False)

    booking_reference: Mapped[Optional[str]] = mapped_column(String(16))
    airline_code: Mapped[Optional[str]] = mapped_column(String(4))
    flight_number: Mapped[Optional[str]] = mapped_column(String(8))
    julian_date: Mapped[Optional[int]] = mapped_column(Integer)
    cabin_class: Mapped[Optional[str]] = mapped_column(String(16))
    seat: Mapped[Optional[str]] = mapped_column(String(8))
    passenger_status: Mapped[Optional[str]] = mapped_column(String(4))

    # locations are flattened into columns, a separate airports table would be the next step
    # if we ever wanted to cache the locations API results in the db
    origin_code: Mapped[Optional[str]] = mapped_column(String(4))
    origin_airport_name: Mapped[Optional[str]] = mapped_column(String(128))
    origin_city_name: Mapped[Optional[str]] = mapped_column(String(128))
    origin_country: Mapped[Optional[str]] = mapped_column(String(128))

    destination_code: Mapped[Optional[str]] = mapped_column(String(4))
    destination_airport_name: Mapped[Optional[str]] = mapped_column(String(128))
    destination_city_name: Mapped[Optional[str]] = mapped_column(String(128))
    destination_country: Mapped[Optional[str]] = mapped_column(String(128))

    boarding_pass: Mapped[BoardingPass] = relationship(back_populates="legs")


Index("boarding_passes_parsed_at", BoardingPass.parsed_at.desc())
Index("boarding_passes_passenger_name", func.lower(BoardingPass.passenger_name))
Index("boarding_pass_legs_boarding_pass_id", BoardingPassLeg.boarding_pass_id)
Index("boarding_pass_legs_airline_code", BoardingPassLeg.airline_code)
