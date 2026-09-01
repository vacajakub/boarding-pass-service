import pypdfium2 as pdfium
import pytest

from tests.data import no_barcode_pdf_bytes, return_pdf_bytes, sample_pdf_bytes
from tests.multi_leg import multi_leg_payload

from boarding_pass_service.bcbp_utils import (
    BarcodeNotFoundError,
    InvalidBcbpError,
    airport_codes,
    boarding_pass_from_decoded,
    cabin_class_for,
    cabin_class_for_value,
    decode_barcode,
    decoded_from_model,
    extract_payloads,
    is_pdf,
    normalize_number,
    read_pdf417_payloads,
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


# --- multiple legs ----------------------------------------------------------------------------
# A multi leg pass is a through checked connection - one check-in, one barcode, several flights.
# Neither sample PDF has one, so the payload is encoded with the same library that decodes it.


@pytest.fixture(scope="module")
def multi_leg_bcbp():
    return decode_barcode(multi_leg_payload())


def test_multi_leg_payload_is_two_legs(multi_leg_bcbp):
    # the digit after M is the number of legs encoded
    assert multi_leg_payload().startswith("M2")
    assert len(multi_leg_bcbp.data.legs) == 2


def test_multi_leg_airport_codes(multi_leg_bcbp):
    # the connecting airport appears as both a destination and an origin, but is resolved once
    assert airport_codes(multi_leg_bcbp) == {"KSC", "PRG", "LHR"}


def test_multi_leg_maps_each_leg_separately(multi_leg_bcbp):
    decoded = to_decoded_bcbp(multi_leg_bcbp, {})

    assert decoded.passenger_name == "CYPRIAN/MICHAL"
    assert len(decoded.legs) == 2

    first, second = decoded.legs
    # order matters, the legs are flown in sequence
    assert (first.origin.code, first.destination.code) == ("KSC", "PRG")
    assert (second.origin.code, second.destination.code) == ("PRG", "LHR")

    # each leg carries its own carrier, cabin and seat
    assert (first.airline_code, second.airline_code) == ("FR", "BA")
    assert (first.cabin_class, second.cabin_class) == (CabinClass.ECONOMY, CabinClass.BUSINESS)
    assert (first.seat, second.seat) == ("29C", "3A")
    assert (first.flight_number, second.flight_number) == ("7774", "857")

    # the booking reference is shared by the whole journey
    assert first.booking_reference == second.booking_reference == "ZKN85B"


def test_multi_leg_model_roundtrip(multi_leg_bcbp):
    decoded = to_decoded_bcbp(multi_leg_bcbp, {})
    model = boarding_pass_from_decoded(decoded, multi_leg_payload())

    # leg_index is what keeps the order in the database
    assert [leg.leg_index for leg in model.legs] == [0, 1]
    assert [leg.airline_code for leg in model.legs] == ["FR", "BA"]
    assert decoded_from_model(model) == decoded


# --- a return journey is two boarding passes, not two legs -------------------------------------


def test_return_pdf_holds_two_separate_passes():
    payloads = read_pdf417_payloads(return_pdf_bytes(), 3.0)

    assert len(payloads) == 2
    # two single leg passes, not one two leg pass
    assert all(payload.startswith("M1") for payload in payloads)

    outbound, inbound = (decode_barcode(payload) for payload in payloads)
    assert len(outbound.data.legs) == len(inbound.data.legs) == 1
    assert outbound.data.passenger_name == inbound.data.passenger_name == "VACA/JAKUB"
    # same booking, reversed route
    assert outbound.data.legs[0].operating_carrier_pnr_code == inbound.data.legs[0].operating_carrier_pnr_code
    assert (outbound.data.legs[0].from_city_airport_code, outbound.data.legs[0].to_city_airport_code) == ("PRG", "BFS")
    assert (inbound.data.legs[0].from_city_airport_code, inbound.data.legs[0].to_city_airport_code) == ("BFS", "PRG")


def test_extract_payloads_takes_the_first_of_several():
    # all pages are scanned, but only the first barcode found is used
    payload = extract_payloads(return_pdf_bytes(), 3.0, 5.0)

    assert payload == read_pdf417_payloads(return_pdf_bytes(), 3.0)[0]

    leg = decode_barcode(payload).data.legs[0]
    assert (leg.from_city_airport_code, leg.to_city_airport_code) == ("PRG", "BFS")
    assert leg.flight_number == "3092"


def test_return_pdf_maps_the_outbound():
    decoded = to_decoded_bcbp(decode_barcode(extract_payloads(return_pdf_bytes(), 3.0, 5.0)), {})
    leg = decoded.legs[0]

    assert decoded.passenger_name == "VACA/JAKUB"
    assert leg.airline_code == "EZY"
    assert leg.flight_number == "3092"
    assert leg.julian_date == 84
    assert leg.seat == "5F"
    # this carrier leaves the compartment code blank, so the mapping falls back instead of guessing
    assert leg.cabin_class == CabinClass.UNKNOWN


# --- a PDF with no barcode on it ----------------------------------------------------------------


def test_pdf_without_any_barcode():
    # a perfectly valid PDF, just not a boarding pass - the retry at a larger scale finds nothing either
    assert read_pdf417_payloads(no_barcode_pdf_bytes(), 3.0) == []

    with pytest.raises(BarcodeNotFoundError):
        extract_payloads(no_barcode_pdf_bytes(), 3.0, 5.0)


def test_pdf_without_any_barcode_is_still_a_pdf():
    # it fails on the barcode, not on the format check
    assert is_pdf("application/pdf", no_barcode_pdf_bytes())


# --- degenerate payloads and fallbacks -----------------------------------------------------------


def test_decode_barcode_raises_on_unparsable_payload():
    # the decoder itself blows up on this one, rather than returning an empty pass
    with pytest.raises(InvalidBcbpError):
        decode_barcode("M9" + "x" * 300)


def test_leg_without_airport_codes_still_maps():
    # a minimal pass, every optional field empty - the mapping must not crash on the missing codes
    bcbp = decode_barcode("M1")
    decoded = to_decoded_bcbp(bcbp, {})

    assert decoded.legs[0].origin.code == ""
    assert decoded.legs[0].destination.code == ""
    assert decoded.legs[0].cabin_class == CabinClass.UNKNOWN


def test_cabin_class_for_value_falls_back_on_unknown_stored_value():
    # a row written by an older version of the mapping must not break the listing
    assert cabin_class_for_value("economy") == CabinClass.ECONOMY
    assert cabin_class_for_value("first_class_ish") == CabinClass.UNKNOWN
    assert cabin_class_for_value(None) == CabinClass.UNKNOWN
