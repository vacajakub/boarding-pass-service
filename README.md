## Boarding pass service

REST API that parses a PDF boarding pass and serves the decoded data as JSON.

### About

The boarding pass is a PDF with an embedded **PDF417** barcode carrying the passenger data in the
IATA **BCBP** (Bar Coded Boarding Pass) format. Parsing therefore has three steps:

1. render the PDF pages with [`pypdfium2`](https://pypi.org/project/pypdfium2/),
2. read the PDF417 barcode off the rendered pages with [`zxing-cpp`](https://pypi.org/project/zxing-cpp/),
3. decode the BCBP payload with [`iata`](https://github.com/jqssun/iata-api).

The barcode carries only the IATA codes of the origin and destination, so they are resolved into
airport/city/country names through the public Locations API
(`https://api.skypicker.com/locations/id?id=PRG`).

FastAPI was picked for the same reasons as in `pdf-service` - async by default, request/response
validation and generated OpenAPI docs for free. Everything on the request path is async
(`asyncpg` + SQLAlchemy 2.x async ORM, `httpx.AsyncClient`), and the one genuinely CPU bound part -
rendering pages and reading the barcode - is pushed to a thread pool so it never blocks the event
loop.

#### DB

Postgres, reached through two SQLAlchemy async engines - a **master** one for writes and a
**slave** one for reads. In docker-compose both point at the same container; in a real deployment
the slave would point at a read replica.

The schema is created by the numbered scripts in `sql/`, which are mounted into
`/docker-entrypoint-initdb.d/` and run by the Postgres image on first start. An alternative would be
a migration tool (alembic) or a startup script. Data lives in the named volume
`postgres-data-local`, so **it survives `docker compose down` / `up`** (use `docker compose down -v`
to wipe it).

Everything lives in the `boarding_pass` schema rather than in `public`. The ORM metadata carries
the schema, so SQLAlchemy emits fully qualified table names and nothing depends on the
`search_path` being right; the connection sets `search_path` as well, so hand written SQL and
`psql` sessions land in the right place too. The name is defined once, in
`boarding_pass_service/models.py`.

Handlers get the session *factory* through `Depends` (see
`boarding_pass_service/dependencies.py`), never an already open `AsyncSession`. The usual
session-per-request dependency checks a connection out of the pool before the handler runs and
holds it until the response is sent; on the parse endpoint that would mean holding one through the
PDF render (~370 ms) and the locations call to do ~12 ms of actual work. Opening the session in the
DAO instead keeps a connection checked out only while a query runs.

Pool sizes are set explicitly rather than left at the SQLAlchemy defaults, because every worker
opens two pools and the total has to fit under the server's `max_connections`. The arithmetic is
spelled out in `boarding_pass_service/config.py`; with the default 8 workers it comes to 80
connections against postgres' default 100.

Two tables: `boarding_passes` (one row per parsed pass, UUID id, `parsed_at`, passenger name and the
raw BCBP payload) and `boarding_pass_legs` (one row per leg). Legs are a separate table because the
`airline_code` filter has to match *any* leg of a pass.

#### Other notes

* Only the **first** PDF417 found is decoded and stored. All pages are scanned though, so the
  barcode may sit on any page of a multi-page document.
* Anything that is not a PDF is rejected with `400` before it ever reaches the renderer - both the
  content type and the `%PDF-` magic bytes are checked.
* Airport names come from the Locations API verbatim, so for example the country of `PRG` comes back
  as `Czechia`, not `Czech Republic`.
* The Locations API is treated as best effort: short timeout, all codes of a request resolved
  concurrently, results cached in process. If it is slow, down, or does not know a code, the parse
  still returns `200` with `airport_name` / `city_name` / `country` as `null`. See the comment in
  `boarding_pass_service/locations.py` for the alternatives (failing the request, or backfilling the
  names later from an async job).
* The raw barcode is stored alongside the decoded data, so a pass can be re-decoded if the mapping
  ever changes.

## How to run

### Run in docker-compose

```sh
docker compose up -d --build     # build and start the app on :8000 and postgres on :9433
docker compose logs -f           # follow the logs
docker compose build             # rebuild only
docker compose down              # stop, keeping the db data
docker compose down -v           # stop and drop the db data as well
```

The host ports are overridable, so the stack can run next to something already holding them
(`pdf-service` uses 9432, hence 9433 here):

```sh
APP_PORT=8080 DB_PORT=9434 docker compose up -d
```

To get into the database:

```sh
docker compose exec db psql "host=db port=9433 user=boarding_pass password=boarding_pass dbname=boarding_pass"
```

### Run in vscode

Open the folder in VS Code and pick *Reopen in Container* - `.devcontainer/` brings up the app
container together with Postgres. Then use the **boarding pass server** launch configuration
(`.vscode/launch.json`) to run the app with the debugger, or **boarding pass server - unit tests**
to run the unit tests.

### Run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # PIP_CONFIG_FILE=/dev/null if the corporate index is unreachable
docker compose up -d db                                     # just the database
CONFFILE=conf/boarding-pass-service.env DB_HOST=localhost \
  .venv/bin/python -m boarding_pass_service.main            # app on :8000 with reload
```

> **Note on DNS.** The compose files build with `network: host` and pin public resolvers for the
> app container. The host `resolv.conf` points at a systemd-resolved stub plus internal resolvers
> that docker cannot use, so without this neither `pip` during the build nor the Locations API call
> at runtime would resolve. Container-to-container names (`db`) keep going through docker's own
> resolver.

### Tests

Unit tests need neither the database nor the network:

```sh
.venv/bin/python -m pytest tests/unit -v
```

No test talks to anything outside the machine it runs on. The locations API is fed canned
responses through `httpx.MockTransport` in the unit tests and swapped out via
`dependency_overrides` in the integration ones, and `tests/conftest.py` enforces that with a
session-wide guard: any lookup of a host other than loopback or the database fails the test with an
explanation. So a slow, rate limiting or unreachable third party can never turn the pipeline red.

Coverage is reported on every run (`--cov` is in the pytest config) and the suite fails below 90%.
The full suite sits around 99%; what is left uncovered is defensive branches. Note that
`tests/unit` alone cannot reach the handlers, so run the whole suite before reading the number.

Test data in `test_data/`:

| file | what it is for |
| --- | --- |
| `boarding_pass.pdf` | one page, one single-leg pass - the happy path |
| `Boarding_Pass_and_return.pdf` | two pages, outbound and return as two separate passes - only the first is processed |
| `sample_not_boarding_pass.pdf` | a valid PDF with no barcode on it - rejected with 422 |

A multi-leg pass (a through-checked connection, one barcode covering several flights) is not among
them, because none of the sample PDFs has one. `tests/multi_leg.py` encodes one with the same
library that decodes it - multi-leg strings copied out of the implementation guide are routinely
mis-transcribed, and the conditional section lengths then drift so every later field decodes into
garbage.

The whole suite, unit and integration, runs against a real Postgres in docker:

```sh
docker compose -f test-docker-compose.yml up --build --abort-on-container-exit --exit-code-from test
docker compose -f test-docker-compose.yml down -v
```

## How to call

Interactive docs are at `http://localhost:8000/docs`.

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

When both filters are given, results have to match all of them; `total` reflects the number of items
matching the applied filters, not the page size.

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

Internal endpoints, meant for k8s probes rather than for the world:

```sh
curl 'http://localhost:8000/liveness'
curl 'http://localhost:8000/readiness'
```
