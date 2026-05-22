"""Admin routes: manual refetch and edge reconciliation.

Protected by Bearer token (ADMIN_TOKEN env var). Returns 403 if no token is
configured — this prevents accidental exposure on deployments that haven't
set the env var.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import text

from wiki_genres.config import get_settings
from wiki_genres.crawler.frontier import enqueue_many
from wiki_genres.db import session_scope
from wiki_genres.loader.loader import resolve_edges

router = APIRouter(prefix="/admin", tags=["admin"])
_bearer = HTTPBearer(auto_error=True)


def verify_admin_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> None:
    settings = get_settings()
    if not settings.admin_token:
        raise HTTPException(status_code=403, detail="Admin access not configured.")
    if credentials.credentials != settings.admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token.")


class RefetchRequest(BaseModel):
    title: str


class RefetchResult(BaseModel):
    enqueued: int
    title: str


class ReconcileResult(BaseModel):
    edges_resolved: int


# ------------------------------------------------------------------ #
# POST /admin/refetch                                                 #
# ------------------------------------------------------------------ #

@router.post("/refetch", response_model=RefetchResult, dependencies=[Depends(verify_admin_token)])
async def refetch(body: RefetchRequest) -> RefetchResult:
    """Enqueue a Wikipedia title for an immediate re-fetch."""
    count = await enqueue_many([body.title], reason="manual")
    return RefetchResult(enqueued=count, title=body.title)


# ------------------------------------------------------------------ #
# POST /admin/reconcile                                               #
# ------------------------------------------------------------------ #

@router.post("/reconcile", response_model=ReconcileResult, dependencies=[Depends(verify_admin_token)])
async def reconcile() -> ReconcileResult:
    """Re-run the edge resolution pass against all unresolved edges."""
    resolved = await resolve_edges()
    return ReconcileResult(edges_resolved=resolved)


# ------------------------------------------------------------------ #
# GET /admin/stats                                                    #
# ------------------------------------------------------------------ #

@router.get("/frontier", dependencies=[Depends(verify_admin_token)])
async def frontier_status() -> dict:
    """Current frontier queue depth and oldest/newest entries."""
    async with session_scope() as session:
        depth = await session.scalar(text("SELECT count(*) FROM wg_frontier"))
        oldest = await session.scalar(
            text("SELECT min(enqueued_at) FROM wg_frontier")
        )
    return {"depth": depth, "oldest_enqueued_at": oldest}
