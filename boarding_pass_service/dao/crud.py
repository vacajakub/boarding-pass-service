from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from boarding_pass_service.models import BoardingPass, BoardingPassLeg


async def insert_boarding_pass(session_factory: async_sessionmaker, boarding_pass: BoardingPass) -> BoardingPass:
    async with session_factory() as session:
        async with session.begin():
            session.add(boarding_pass)
        # server defaults (id, parsed_at) are only known after the flush
        await session.refresh(boarding_pass, ["id", "parsed_at"])
        return boarding_pass


async def list_boarding_passes(
    session_factory: async_sessionmaker,
    limit: int,
    offset: int,
    passenger_name: Optional[str] = None,
    airline_code: Optional[str] = None,
) -> Tuple[List[BoardingPass], int]:
    filters = []
    if passenger_name:
        # case-insensitive substring match
        filters.append(BoardingPass.passenger_name.ilike(f"%{passenger_name}%"))
    if airline_code:
        # exact match on the airline code of any leg of the boarding pass
        filters.append(
            select(BoardingPassLeg.id)
            .where(
                BoardingPassLeg.boarding_pass_id == BoardingPass.id,
                BoardingPassLeg.airline_code == airline_code,
            )
            .exists()
        )

    query = select(BoardingPass).where(*filters).order_by(BoardingPass.parsed_at.desc(), BoardingPass.id.desc())
    count_query = select(func.count()).select_from(BoardingPass).where(*filters)

    async with session_factory() as session:
        # total has to reflect the filters, not the page
        total = await session.scalar(count_query)
        items = (await session.scalars(query.limit(limit).offset(offset))).all()
        return list(items), total or 0


async def check_db(session_factory: async_sessionmaker) -> bool:
    async with session_factory() as session:
        return await session.scalar(select(1)) == 1
