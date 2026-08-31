"""A two leg boarding pass, for the cases the sample PDFs cannot reach.

Both sample PDFs carry single leg passes (the return journey is a second pass, not a second leg),
and multi leg barcodes copied from the implementation guide are notoriously mis-transcribed - the
conditional section lengths drift and every field after them decodes into garbage. Encoding it with
the same library that decodes it keeps the fixture honest.

A real multi leg pass is a through checked connection: one check-in, one barcode, KSC-PRG-LHR.
"""

from datetime import datetime, timezone

from iata.bcbp import BarcodedBoardingPass, BoardingPassData, BoardingPassMetaData, Leg, encode

REFERENCE_YEAR = 2025


def multi_leg_payload() -> str:
    return encode(
        BarcodedBoardingPass(
            meta=BoardingPassMetaData(version_number=2),
            data=BoardingPassData(
                passenger_name="CYPRIAN/MICHAL",
                legs=[
                    Leg(
                        operating_carrier_pnr_code="ZKN85B",
                        from_city_airport_code="KSC",
                        to_city_airport_code="PRG",
                        operating_carrier_designator="FR",
                        flight_number="7774",
                        date_of_flight=datetime(REFERENCE_YEAR, 4, 15, tzinfo=timezone.utc),
                        compartment_code="Y",
                        seat_number="29C",
                        check_in_sequence_number="0025",
                        passenger_status="1",
                    ),
                    Leg(
                        operating_carrier_pnr_code="ZKN85B",
                        from_city_airport_code="PRG",
                        to_city_airport_code="LHR",
                        operating_carrier_designator="BA",
                        flight_number="857",
                        date_of_flight=datetime(REFERENCE_YEAR, 4, 15, tzinfo=timezone.utc),
                        compartment_code="C",
                        seat_number="3A",
                        check_in_sequence_number="0026",
                        passenger_status="1",
                    ),
                ],
            ),
        )
    )
