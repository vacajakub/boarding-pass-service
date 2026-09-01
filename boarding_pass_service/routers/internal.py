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
        await check_db(db)
    except Exception as e:
        logger.exception("Server not ready: %s", e)
        raise HTTPException(status_code=412, detail="Not Ready") from e

    return "I'm ready!"


@router.get("/liveness", response_model=str)
async def liveness() -> str:
    # deliberately does not touch the database - a db blip must not get healthy pods restarted
    return "I'm alive!"
