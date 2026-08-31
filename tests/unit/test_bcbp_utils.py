import pypdfium2 as pdfium
import pytest

from tests.data import sample_pdf_bytes

from boarding_pass_service.bcbp_utils import (
    BarcodeNotFoundError,
    InvalidBcbpError,
    airport_codes,
    boarding_pass_from_decoded,
    cabin_class_for,
    decode_barcode,
    decoded_from_model,
    extract_payloads,
    is_pdf,
    normalize_number,
    to_decoded_bcbp,
)
from boarding_pass_service.schemas import CabinClass, Location

# tests for the pdf -> barcode -> BCBP -> response chain, on the annotated sample boarding pass
# ideally this would run over a whole annotated set of boarding passes from different airlines


@pytest.fixture(scope="module")
def payload() -> str:
    return extract_payloads(sample_pdf_bytes(), 3.0, 5.0)


def test_is_pdf():
    assert is_pdf("application/pdf", b"%PDF-1.4 ...")
    assert is_pdf(None, b"%PDF-1.7 ...")
    # content type says pdf but the bytes do not
    assert not is_pdf("application/pdf", b"not a pdf at all")
    assert not is_pdf("text/plain", b"%PDF-1.4 ...")
    assert not is_pdf("image/png", b"\x89PNG\r\n")


def test_extract_first_pdf417(payload):
    # M == mandatory items, 1 == one leg encoded
    assert payload.startswith("M1")


def test_extract_first_pdf417_without_barcode():
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(300, 300)
    empty_pdf = pdf.save_to_bytes() if hasattr(pdf, "save_to_bytes") else None
    if empty_pdf is None:
        import io

        buffer = io.BytesIO()
        pdf.save(buffer)
        empty_pdf = buffer.getvalue()

    with pytest.raises(BarcodeNotFoundError):
        extract_payloads(empty_pdf, 2.0, None)


def test_decode_barcode(payload):
    bcbp = decode_barcode(payload)

    assert bcbp.data.passenger_name == "CYPRIAN/MICHAL"
    assert len(bcbp.data.legs) == 1

    leg = bcbp.data.legs[0]
    assert leg.operating_carrier_pnr_code == "ZKN85B"
    assert leg.operating_carrier_designator == "FR"
    assert leg.from_city_airport_code == "KSC"
    assert leg.to_city_airport_code == "PRG"


def test_decode_barcode_invalid():
    with pytest.raises(InvalidBcbpError):
        decode_barcode("definitely not a boarding pass")


def test_to_decoded_bcbp(payload):
    bcbp = decode_barcode(payload)

    assert airport_codes(bcbp) == {"KSC", "PRG"}

    decoded = to_decoded_bcbp(
        bcbp,
        {
            "KSC": Location(code="KSC", airport_name="Košice International", city_name="Košice", country="Slovakia"),
            "PRG": Location(
                code="PRG", airport_name="Václav Havel Airport Prague", city_name="Prague", country="Czechia"
            ),
        },
    )

    assert decoded.passenger_name == "CYPRIAN/MICHAL"
    leg = decoded.legs[0]
    assert leg.booking_reference == "ZKN85B"
    assert leg.airline_code == "FR"
    assert leg.flight_number == "7774"
    assert leg.julian_date == 105
    assert leg.cabin_class == CabinClass.ECONOMY
    assert leg.seat == "29C"
    assert leg.passenger_status == "1"
    assert leg.origin.code == "KSC"
    assert leg.origin.city_name == "Košice"
    assert leg.destination.code == "PRG"
    assert leg.destination.airport_name == "Václav Havel Airport Prague"


def test_to_decoded_bcbp_without_locations(payload):
    # the locations API is best effort, an unresolved code still yields a full response
    decoded = to_decoded_bcbp(decode_barcode(payload), {})
    leg = decoded.legs[0]

    assert leg.origin.code == "KSC"
    assert leg.origin.airport_name is None
    assert leg.destination.country is None


def test_model_roundtrip(payload):
    decoded = to_decoded_bcbp(decode_barcode(payload), {})
    model = boarding_pass_from_decoded(decoded, payload)

    assert model.raw_barcode == payload
    assert model.passenger_name == "CYPRIAN/MICHAL"
    assert len(model.legs) == 1
    assert model.legs[0].leg_index == 0

    # what the listing endpoint renders has to match what the parse endpoint returned
    assert decoded_from_model(model) == decoded


@pytest.mark.parametrize(
    "code,expected",
    [
        ("Y", CabinClass.ECONOMY),
        ("m", CabinClass.ECONOMY),
        ("W", CabinClass.PREMIUM_ECONOMY),
        ("C", CabinClass.BUSINESS),
        ("F", CabinClass.FIRST),
        ("1", CabinClass.UNKNOWN),
        (None, CabinClass.UNKNOWN),
    ],
)
def test_cabin_class_for(code, expected):
    assert cabin_class_for(code) == expected


@pytest.mark.parametrize(
    "value,expected",
    [("07774", "7774"), ("029C", "29C"), ("0834 ", "834"), ("00000", None), (None, None)],
)
def test_normalize_number(value, expected):
    assert normalize_number(value) == expected
