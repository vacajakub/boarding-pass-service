import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile
from starlette import status
from starlette.concurrency import run_in_threadpool

from boarding_pass_service.bcbp_utils import (
    BarcodeNotFoundError,
    InvalidBcbpError,
    airport_codes,
    boarding_pass_from_decoded,
    decode_barcode,
    decoded_from_model,
    extract_payloads,
    is_pdf,
    to_decoded_bcbp,
)
from boarding_pass_service.dao.crud import insert_boarding_pass, list_boarding_passes
from boarding_pass_service.dependencies import AppSettings, Locations, SessionMaster, SessionSlave
from boarding_pass_service.schemas import (
    BoardingPassListItem,
    BoardingPassListResponse,
    ParseBoardingPassResponse,
)

router = APIRouter(tags=["boarding passes"])
logger = logging.getLogger("boarding-pass-service.boarding_pass")


@router.post("/boarding-pass/parse-from-file", response_model=ParseBoardingPassResponse)
async def parse_from_file(
    file: UploadFile,
    settings: AppSettings,
    locations_client: Locations,
    db: SessionMaster,
) -> ParseBoardingPassResponse:
    data = await file.read()

    # safety check
    if len(data) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File is larger than the {settings.max_upload_size_bytes} B limit",
        )

    # early exit on anything that is not a PDF, before we hand the bytes to the renderer
    if not is_pdf(file.content_type, data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file format, expected a PDF")

    try:
        # rendering the pages and reading the barcode is CPU bound and blocking,
        # so it goes to the thread pool instead of stalling the event loop
        # Also this would be better suited for async task queue for big files
        payload = await run_in_threadpool(
            extract_payloads, data, settings.pdf_render_scale, settings.pdf_render_scale_retry
        )
        bcbp = decode_barcode(payload)
    except BarcodeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="No PDF417 boarding pass barcode found in the PDF"
        ) from e
    except InvalidBcbpError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Barcode does not contain valid BCBP data"
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error while parsing boarding pass: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to parse boarding pass"
        ) from e

    # best effort enrichment, the codes of all legs are resolved in one concurrent batch
    locations = await locations_client.resolve(airport_codes(bcbp))
    decoded = to_decoded_bcbp(bcbp, locations)

    try:
        # the session is opened here, not at the start of the request, so the connection is not
        # held through the pdf parsing and the locations lookup above
        await insert_boarding_pass(db, boarding_pass_from_decoded(decoded, payload))
    except Exception as e:
        logger.error("Error while storing boarding pass: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to store boarding pass"
        ) from e

    return ParseBoardingPassResponse(decoded_bcbp=decoded)


@router.get("/boarding-passes", response_model=BoardingPassListResponse)
async def get_boarding_passes(
    db: SessionSlave,
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    passenger_name: Optional[str] = Query(None, description="Case-insensitive substring match on the passenger name"),
    airline_code: Optional[str] = Query(None, description="Exact match on airline code for any leg, e.g. FR"),
) -> BoardingPassListResponse:
    # reads go to the slave
    items, total = await list_boarding_passes(db, limit, offset, passenger_name, airline_code)

    return BoardingPassListResponse(
        items=[
            BoardingPassListItem(id=item.id, parsed_at=item.parsed_at, decoded_bcbp=decoded_from_model(item))
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
