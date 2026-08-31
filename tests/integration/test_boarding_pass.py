from tests.data import SAMPLE_PDF_PATH, sample_pdf_bytes

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


def parse_sample(test_app):
    with SAMPLE_PDF_PATH.open("rb") as file:
        return test_app.post(
            "/boarding-pass/parse-from-file",
            files={"file": ("boarding_pass.pdf", file, "application/pdf")},
        )


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
    # a truncated but still pdf-looking file, no readable PDF417 in it
    response = test_app.post(
        "/boarding-pass/parse-from-file",
        files={"file": ("empty.pdf", sample_pdf_bytes()[:200], "application/pdf")},
    )

    assert response.status_code in (422, 500)


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
