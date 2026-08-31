import logging

from fastapi import APIRouter, HTTPException

from boarding_pass_service.dao.crud import check_db
from boarding_pass_service.dependencies import SessionSlave

router = APIRouter(tags=["internal"])
logger = logging.getLogger("boarding-pass-service.internal")


# internal routes for example for k8s liveness, readiness, metrics etc. normally should not be exposed to the world
@router.get("/readiness", response_model=str)
async def readiness(db: SessionSlave) -> str:
    try:
        if await check_db(db):
            return "I'm ready!"
        raise HTTPException(status_code=412, detail="Not Ready")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Server not ready: %s", e)
        raise HTTPException(status_code=412, detail="Not Ready") from e


@router.get("/liveness", response_model=str)
async def liveness() -> str:
    # simply returns 200 if server is running
    return "I'm alive!"
