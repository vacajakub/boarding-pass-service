import logging
from typing import Dict, List, Optional

import pypdfium2 as pdfium
import zxingcpp
from iata.bcbp import BarcodedBoardingPass, decode

from boarding_pass_service.models import BoardingPass, BoardingPassLeg
from boarding_pass_service.schemas import CabinClass, DecodedBcbp, Leg, Location

logger = logging.getLogger("boarding-pass-service.bcbp_utils")

PDF_MAGIC = b"%PDF-"
PDF_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/acrobat", "text/pdf"})

# IATA compartment (cabin) codes, RBDs grouped into the classes we expose
CABIN_CLASS_BY_COMPARTMENT_CODE = {
    **{code: CabinClass.FIRST for code in "FAPRO"},
    **{code: CabinClass.BUSINESS for code in "JCDIZ"},
    **{code: CabinClass.PREMIUM_ECONOMY for code in "WE"},
    **{code: CabinClass.ECONOMY for code in "YBHKLMNQSTVXGU"},
}


class BarcodeNotFoundError(Exception):
    """No PDF417 barcode could be decoded from the document."""


class InvalidBcbpError(Exception):
    """A PDF417 was found but its payload is not a valid BCBP string."""


def is_pdf(content_type: Optional[str], data: bytes) -> bool:
    """Early format check - content type is client supplied, so the magic bytes decide."""
    if content_type and content_type.split(";")[0].strip().lower() not in PDF_CONTENT_TYPES:
        return False
    return data.startswith(PDF_MAGIC)


def read_pdf417_payloads(pdf_data: bytes, scale: float) -> List[str]:
    """Render every page and read the PDF417 barcodes off it."""
    payloads: List[str] = []
    pdf = pdfium.PdfDocument(pdf_data)
    try:
        for page_number, page in enumerate(pdf, 1):
            image = page.render(scale=scale).to_pil()
            # we care only about PDF417, restricting the formats also keeps the reader fast (by requirements)
            # in prod we might also take Aztec etc. if we wanted to support boarding passes from other sources
            barcodes = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.PDF417)
            for barcode in barcodes:
                text = barcode.text or (barcode.bytes or b"").decode("latin-1")
                if text:
                    payloads.append(text)
            logger.debug("Page %s: found %s PDF417 barcode(s)", page_number, len(barcodes))
    finally:
        pdf.close()

    return payloads


def extract_payloads(pdf_data: bytes, scale: float, retry_scale: Optional[float] = None) -> str:
    """All pages are scanned, but currently only the first barcode found is used."""
    # Requirement specified that the parse-from-file endpoint returns only 1 decoded bcbp,
    # so we do not return a list of barcodes here.
    # If the requirement changes, this function can be changed to return a list of payloads instead.
    # Also, if we really want the first one, we can break after we find the first one,
    # but for now we read all pages and all barcodes, and log if there are multiple.
    payloads = read_pdf417_payloads(pdf_data, scale)

    if not payloads and retry_scale and retry_scale > scale:
        # low resolution barcodes sometimes need a bigger render, worth the second, slower pass
        logger.info("No PDF417 at scale %s, retrying at scale %s", scale, retry_scale)
        payloads = read_pdf417_payloads(pdf_data, retry_scale)

    if not payloads:
        raise BarcodeNotFoundError("No PDF417 barcode found in the document")

    if len(payloads) > 1:
        logger.info("Found %s PDF417 barcodes, using the first one", len(payloads))

    return payloads[0]


def decode_barcode(payload: str) -> BarcodedBoardingPass:
    try:
        bcbp = decode(payload)
    except Exception as e:
        raise InvalidBcbpError("Barcode payload is not a valid BCBP string") from e

    if bcbp.data is None or not bcbp.data.legs:
        raise InvalidBcbpError("Barcode payload does not contain any boarding pass leg")

    return bcbp


def cabin_class_for(compartment_code: Optional[str]) -> CabinClass:
    if not compartment_code:
        return CabinClass.UNKNOWN
    return CABIN_CLASS_BY_COMPARTMENT_CODE.get(compartment_code.strip().upper(), CabinClass.UNKNOWN)


def normalize_number(value: Optional[str]) -> Optional[str]:
    """BCBP zero pads flight numbers and seats to a fixed width, `07774` -> `7774`."""
    if value is None:
        return None
    stripped = value.strip().lstrip("0")
    return stripped or None


def airport_codes(bcbp: BarcodedBoardingPass) -> set:
    codes = set()
    for leg in bcbp.data.legs:
        codes.update(code for code in (leg.from_city_airport_code, leg.to_city_airport_code) if code)
    return codes


def to_decoded_bcbp(bcbp: BarcodedBoardingPass, locations: Dict[str, Location]) -> DecodedBcbp:
    legs = []
    for leg in bcbp.data.legs:
        legs.append(
            Leg(
                booking_reference=leg.operating_carrier_pnr_code,
                airline_code=leg.operating_carrier_designator,
                flight_number=normalize_number(leg.flight_number),
                # the barcode carries the day of the year, the decoder turns it into a date for us
                julian_date=leg.date_of_flight.timetuple().tm_yday if leg.date_of_flight else None,
                cabin_class=cabin_class_for(leg.compartment_code),
                seat=normalize_number(leg.seat_number),
                passenger_status=leg.passenger_status,
                origin=_location(locations, leg.from_city_airport_code),
                destination=_location(locations, leg.to_city_airport_code),
            )
        )

    return DecodedBcbp(passenger_name=bcbp.data.passenger_name, legs=legs)


def _location(locations: Dict[str, Location], code: Optional[str]) -> Location:
    if not code:
        return Location(code="")
    return locations.get(code, Location(code=code))


def boarding_pass_from_decoded(decoded: DecodedBcbp, raw_barcode: str) -> BoardingPass:
    return BoardingPass(
        passenger_name=decoded.passenger_name,
        raw_barcode=raw_barcode,
        legs=[
            BoardingPassLeg(
                leg_index=index,
                booking_reference=leg.booking_reference,
                airline_code=leg.airline_code,
                flight_number=leg.flight_number,
                julian_date=leg.julian_date,
                cabin_class=leg.cabin_class.value,
                seat=leg.seat,
                passenger_status=leg.passenger_status,
                origin_code=leg.origin.code,
                origin_airport_name=leg.origin.airport_name,
                origin_city_name=leg.origin.city_name,
                origin_country=leg.origin.country,
                destination_code=leg.destination.code,
                destination_airport_name=leg.destination.airport_name,
                destination_city_name=leg.destination.city_name,
                destination_country=leg.destination.country,
            )
            for index, leg in enumerate(decoded.legs)
        ],
    )


def decoded_from_model(boarding_pass: BoardingPass) -> DecodedBcbp:
    """Same response shape for the listing endpoint as for the parse endpoint."""
    return DecodedBcbp(
        passenger_name=boarding_pass.passenger_name,
        legs=[
            Leg(
                booking_reference=leg.booking_reference,
                airline_code=leg.airline_code,
                flight_number=leg.flight_number,
                julian_date=leg.julian_date,
                cabin_class=cabin_class_for_value(leg.cabin_class),
                seat=leg.seat,
                passenger_status=leg.passenger_status,
                origin=Location(
                    code=leg.origin_code or "",
                    airport_name=leg.origin_airport_name,
                    city_name=leg.origin_city_name,
                    country=leg.origin_country,
                ),
                destination=Location(
                    code=leg.destination_code or "",
                    airport_name=leg.destination_airport_name,
                    city_name=leg.destination_city_name,
                    country=leg.destination_country,
                ),
            )
            for leg in boarding_pass.legs
        ],
    )


def cabin_class_for_value(value: Optional[str]) -> CabinClass:
    try:
        return CabinClass(value)
    except ValueError:
        return CabinClass.UNKNOWN
