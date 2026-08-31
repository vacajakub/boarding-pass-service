import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from boarding_pass_service.app_state import AppState
from boarding_pass_service.routers import boarding_pass, internal

tags_metadata = [
    {
        "name": "boarding passes",
        "description": "Parsing of PDF boarding passes with an embedded IATA BCBP PDF417 barcode",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("boarding-pass-service")
    await app.state.setup()
    logger.info("Started")

    yield

    logger.info("Shutting down")

    # don't forget to close pools and clients
    await app.state.teardown()
    logger.info("Shutdown end")


app = FastAPI(
    title="Boarding pass service",
    description="Server for parsing of PDF boarding passes",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)
app.state = AppState()
app.include_router(boarding_pass.router)
app.include_router(internal.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "boarding_pass_service.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_config=None,
        timeout_keep_alive=10,
    )
