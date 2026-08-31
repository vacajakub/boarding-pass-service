from tests.data import NO_BARCODE_PDF_PATH, RETURN_PDF_PATH, SAMPLE_PDF_PATH
from tests.multi_leg import multi_leg_payload

from boarding_pass_service.bcbp_utils import boarding_pass_from_decoded, decode_barcode, to_decoded_bcbp
from boarding_pass_service.dao.crud import insert_boarding_pass
from boarding_pass_service.main import app

EXPECTED_DECODED_BCBP = {
    "passenger_name": "CYPRIAN/MICHAL",
    "legs": [
        {
            "booking_reference": "ZKN85B",
            "airline_code": "FR",
            "flight_number": "7774",
            "julian_date": 105,
            "cabin_class": "economy",
            "seat": "29C",
            "passenger_status": "1",
            "origin": {
                "code": "KSC",
                "airport_name": "Košice International",
                "city_name": "Košice",
                "country": "Slovakia",
            },
            "destination": {
                "code": "PRG",
                "airport_name": "Václav Havel Airport Prague",
                "city_name": "Prague",
                "country": "Czechia",
            },
        }
    ],
}


def post_pdf(test_app, path):
    with path.open("rb") as file:
        return test_app.post(
            "/boarding-pass/parse-from-file",
            files={"file": (path.name, file, "application/pdf")},
        )


def parse_sample(test_app):
    return post_pdf(test_app, SAMPLE_PDF_PATH)


def test_liveness(test_app):
    response = test_app.get("/liveness")
    assert response.status_code == 200


def test_readiness(test_app):
    response = test_app.get("/readiness")
    assert response.status_code == 200


def test_parse_from_file(test_app):
    response = parse_sample(test_app)

    assert response.status_code == 200
    assert response.json() == {"decoded_bcbp": EXPECTED_DECODED_BCBP}


def test_parse_from_file_rejects_non_pdf(test_app):
    response = test_app.post(
        "/boarding-pass/parse-from-file",
        files={"file": ("not_a_pdf.txt", b"just some text", "text/plain")},
    )

    assert response.status_code == 400


def test_parse_from_file_rejects_pdf_without_barcode(test_app):
    # a perfectly valid PDF that simply is not a boarding pass
    response = post_pdf(test_app, NO_BARCODE_PDF_PATH)

    assert response.status_code == 422
    assert "PDF417" in response.json()["detail"]


def test_list_boarding_passes(test_app):
    assert parse_sample(test_app).status_code == 200

    response = test_app.get("/boarding-passes", params={"limit": 20, "offset": 0})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["decoded_bcbp"] == EXPECTED_DECODED_BCBP
    assert item["id"]
    assert item["parsed_at"].endswith("Z")


def test_list_boarding_passes_empty(test_app):
    body = test_app.get("/boarding-passes").json()

    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_list_boarding_passes_filters(test_app):
    assert parse_sample(test_app).status_code == 200

    # case insensitive substring match on the passenger name
    assert test_app.get("/boarding-passes", params={"passenger_name": "cyprian"}).json()["total"] == 1
    assert test_app.get("/boarding-passes", params={"passenger_name": "MICHAL"}).json()["total"] == 1
    assert test_app.get("/boarding-passes", params={"passenger_name": "novak"}).json()["total"] == 0

    # exact match on the airline code of any leg
    assert test_app.get("/boarding-passes", params={"airline_code": "FR"}).json()["total"] == 1
    assert test_app.get("/boarding-passes", params={"airline_code": "XX"}).json()["total"] == 0
    assert test_app.get("/boarding-passes", params={"airline_code": "f"}).json()["total"] == 0

    # both filters have to match at the same time
    assert (
        test_app.get("/boarding-passes", params={"passenger_name": "cyprian", "airline_code": "FR"}).json()["total"]
        == 1
    )
    assert (
        test_app.get("/boarding-passes", params={"passenger_name": "cyprian", "airline_code": "XX"}).json()["total"]
        == 0
    )


def test_list_boarding_passes_pagination(test_app):
    for _ in range(3):
        assert parse_sample(test_app).status_code == 200

    first_page = test_app.get("/boarding-passes", params={"limit": 2, "offset": 0}).json()
    second_page = test_app.get("/boarding-passes", params={"limit": 2, "offset": 2}).json()

    # total reflects all matching items, not the page size
    assert first_page["total"] == 3
    assert second_page["total"] == 3
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 1

    ids = [item["id"] for item in first_page["items"] + second_page["items"]]
    assert len(set(ids)) == 3


def test_list_boarding_passes_validates_params(test_app):
    assert test_app.get("/boarding-passes", params={"limit": 0}).status_code == 422
    assert test_app.get("/boarding-passes", params={"offset": -1}).status_code == 422


# --- a return journey: two boarding passes in one PDF, only the first is processed --------------


def test_parse_return_pdf_uses_only_the_first_pass(test_app):
    response = post_pdf(test_app, RETURN_PDF_PATH)

    assert response.status_code == 200
    decoded = response.json()["decoded_bcbp"]

    # the outbound, from the first page
    assert decoded["passenger_name"] == "VACA/JAKUB"
    assert len(decoded["legs"]) == 1
    leg = decoded["legs"][0]
    assert (leg["origin"]["code"], leg["destination"]["code"]) == ("PRG", "BFS")
    assert leg["flight_number"] == "3092"
    # the carrier leaves the compartment code blank, the mapping does not guess
    assert leg["cabin_class"] == "unknown"


def test_parse_return_pdf_stores_only_the_first_pass(test_app):
    assert post_pdf(test_app, RETURN_PDF_PATH).status_code == 200

    body = test_app.get("/boarding-passes").json()

    # the return leg on page two is read and logged, but deliberately not stored
    assert body["total"] == 1
    assert body["items"][0]["decoded_bcbp"]["legs"][0]["destination"]["code"] == "BFS"


# --- multiple legs ------------------------------------------------------------------------------
# The sample PDFs are all single leg, so the pass is stored through the DAO directly. This is the
# only way to reach leg ordering and the "any leg" airline filter.


def store_multi_leg(test_app):
    async def store():
        decoded = to_decoded_bcbp(decode_barcode(multi_leg_payload()), {})
        await insert_boarding_pass(app.state.session_master, boarding_pass_from_decoded(decoded, multi_leg_payload()))

    test_app.portal.call(store)


def test_multi_leg_pass_is_listed_with_legs_in_order(test_app):
    store_multi_leg(test_app)

    body = test_app.get("/boarding-passes").json()

    assert body["total"] == 1
    legs = body["items"][0]["decoded_bcbp"]["legs"]
    assert len(legs) == 2
    assert [leg["airline_code"] for leg in legs] == ["FR", "BA"]
    assert [(leg["origin"]["code"], leg["destination"]["code"]) for leg in legs] == [
        ("KSC", "PRG"),
        ("PRG", "LHR"),
    ]
    assert [leg["cabin_class"] for leg in legs] == ["economy", "business"]


def test_airline_code_filter_matches_any_leg(test_app):
    store_multi_leg(test_app)

    # the first leg
    assert test_app.get("/boarding-passes", params={"airline_code": "FR"}).json()["total"] == 1
    # and the second one - this is what the separate legs table is for
    assert test_app.get("/boarding-passes", params={"airline_code": "BA"}).json()["total"] == 1
    # a carrier on neither leg
    assert test_app.get("/boarding-passes", params={"airline_code": "LH"}).json()["total"] == 0


def test_filters_combine_across_passenger_and_any_leg(test_app):
    store_multi_leg(test_app)
    assert parse_sample(test_app).status_code == 200

    # two passes stored, only the multi leg one flies BA
    assert test_app.get("/boarding-passes").json()["total"] == 2
    assert test_app.get("/boarding-passes", params={"airline_code": "BA"}).json()["total"] == 1
    # FR is the first leg of the multi leg pass and the only leg of the sample
    assert test_app.get("/boarding-passes", params={"airline_code": "FR"}).json()["total"] == 2
    assert (
        test_app.get("/boarding-passes", params={"passenger_name": "cyprian", "airline_code": "BA"}).json()["total"]
        == 1
    )
