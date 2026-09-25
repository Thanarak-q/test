from fastapi import APIRouter

from app.envelope import EnvelopeRoute

router = APIRouter(tags=["health"], route_class=EnvelopeRoute)


@router.get("/health", operation_id="getHealth")
async def health() -> dict[str, str]:
    return {"status": "ok"}
