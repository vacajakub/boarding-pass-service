## Boarding pass service

REST API that parses a PDF boarding pass and serves the decoded data as JSON.

Once the app is running, interactive documentation is at http://localhost:8000/docs.

### About

The boarding pass is a PDF with an embedded PDF417 barcode holding the passenger data in the IATA
BCBP (Bar Coded Boarding Pass) format, so parsing it takes three steps:

1. render the pages with [`pypdfium2`](https://pypi.org/project/pypdfium2/),
2. read the PDF417 barcode off them with [`zxing-cpp`](https://pypi.org/project/zxing-cpp/),
3. decode the BCBP payload with [`iata`](https://github.com/jqssun/iata-api).

The barcode carries only the IATA codes of the origin and destination, so the airport, city and
country names are looked up in the public Locations API
(`https://api.skypicker.com/locations/id?id=PRG`).

Written with FastAPI - async by default, request and response validation and generated OpenAPI docs
for free. The request path is async throughout (`asyncpg` with the SQLAlchemy 2.x async ORM,
`httpx` for the Locations API); rendering the PDF and reading the barcode is the one CPU bound part
and runs in a thread pool so it does not block the event loop.

#### DB

Postgres. The schema is created automatically using mounts to docker-entrypoint, alternatively a
startup script from the app could be run. Table and schema definitions are in the `/sql` folder,
everything lives in the `boarding_pass` schema.

Data is kept in a named volume, so it survives `docker compose down` and `up`. Use
`docker compose down -v` to drop it.

Two tables: `boarding_passes`, one row per parsed pass, and `boarding_pass_legs`, one row per leg.
Legs are separate because the `airline_code` filter has to match any leg of a pass.

Reads go to a slave engine and writes to a master one. In docker-compose both point at the same
container, in a real deployment the slave would point at a read replica.

#### Other notes

I left comments through the code in places where I would do something differently if this were to
go to production.

- Only the first PDF417 found is decoded and stored. All pages are scanned though, so the barcode
  may sit on any page of a multi-page document. A return journey is two boarding passes rather than
  one two-leg pass, so for such a PDF only the outbound is kept.
- Anything that is not a PDF is rejected with `400` before it reaches the renderer.
- The Locations API is best effort. If it is slow, down or does not know a code, the parse still
  returns `200` with `airport_name`, `city_name` and `country` as `null`. In production these could
  be backfilled later from a job, which would also pick up airports whose details change.
- Names come from the Locations API verbatim, so the country of `PRG` comes back as `Czechia`
  rather than `Czech Republic`.
- The raw barcode is stored next to the decoded data, so a pass can be re-decoded if the mapping
  ever changes.

## How to run

### Run in docker-compose

Run in docker compose by running `docker compose up -d --build`, the app comes up on port 8000 and
postgres on 9433.

In case of changes to code, run `docker compose up -d --build` again.

If you want to view the logs run `docker compose logs -f`

If you want to look into the database run `docker compose exec db sh` and then
`psql "host=db port=9433 user=boarding_pass password=boarding_pass dbname=boarding_pass"`

Stop and remove by `docker compose down`, add `-v` to drop the database data as well.

Host ports are overridable if something already listens on them:

```sh
APP_PORT=8080 DB_PORT=9434 docker compose up -d
```

### Run in vscode

Dev container plugin in vscode is needed.
Open folder in vscode, then click on open in devcontainer and you are ready to go and debug. Just
launch app (or unit tests) through launch configuration.

### Run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
docker compose up -d db
CONFFILE=conf/boarding-pass-service.env DB_HOST=localhost \
  .venv/bin/python -m boarding_pass_service.main
```

## How to test

Unit tests need neither the database nor the network:

```sh
.venv/bin/python -m pytest tests/unit -v --no-cov
```

The whole suite, unit and integration, runs against a real Postgres in docker:

```sh
docker compose -f test-docker-compose.yml up --build --abort-on-container-exit --exit-code-from test
docker compose -f test-docker-compose.yml down -v
```

No test talks to anything outside the machine it runs on - the Locations API is mocked everywhere
and `tests/conftest.py` enforces it, so a third party being down cannot turn the pipeline red.
Coverage is reported on every run and the suite fails below 90%.

Test data in `test_data/`:

| file | what it is for |
| --- | --- |
| `boarding_pass.pdf` | one page, one single-leg pass - the happy path |
| `Boarding_Pass_and_return.pdf` | outbound and return on two pages - only the first is processed |
| `sample_not_boarding_pass.pdf` | a valid PDF with no barcode on it - rejected with `422` |

None of them is a multi-leg pass, so `tests/multi_leg.py` encodes one with the same library that
decodes it.

## How to call

Once app is running, interactive documentation can be found at http://localhost:8000/docs.

Alternatively you can call endpoints via curl:

Parse a boarding pass:

```sh
curl -X POST \
  'http://localhost:8000/boarding-pass/parse-from-file' \
  -H 'accept: application/json' \
  -H 'Content-Type: multipart/form-data' \
  -F 'file=@test_data/boarding_pass.pdf;type=application/pdf'
```

```json
{
  "decoded_bcbp": {
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
          "country": "Slovakia"
        },
        "destination": {
          "code": "PRG",
          "airport_name": "Václav Havel Airport Prague",
          "city_name": "Prague",
          "country": "Czechia"
        }
      }
    ]
  }
}
```

List the boarding passes parsed so far, newest first:

```sh
curl -X GET \
  'http://localhost:8000/boarding-passes?limit=20&offset=0&passenger_name=CYPRIAN&airline_code=FR' \
  -H 'accept: application/json'
```

| Parameter | Type | Description |
| --- | --- | --- |
| `limit` | integer | Page size, default 20, max 100. |
| `offset` | integer | Number of items to skip, default 0. |
| `passenger_name` | string | Case-insensitive substring match on the passenger name. |
| `airline_code` | string | Exact match on the airline code of any leg, e.g. `FR`. |

When both filters are given results have to match all of them, and `total` reflects the number of
items matching the filters rather than the page size.

```json
{
  "items": [
    {
      "id": "b7d1f0c2-9a3e-4f11-8c0d-2b5e6a7c9d10",
      "parsed_at": "2026-08-10T09:14:22Z",
      "decoded_bcbp": { "... same structure as above ..." }
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

Internal endpoints, for k8s probes rather than for the world:

```sh
curl 'http://localhost:8000/liveness'
curl 'http://localhost:8000/readiness'
```
