from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.capabilities.schemas import (
    CapabilityCreate,
    CapabilityDeleteResponse,
    CapabilityRead,
    CapabilityUpdate,
    ModelProviderCheckResponse,
    ModelProviderDiscoverResponse,
    ModelProviderProbeRequest,
)
from app.capabilities.services.capabilities import CapabilityService
from app.capabilities.services.model_providers import (
    ModelProviderService,
    UnsupportedModelProviderModeError,
)
from app.db.session import get_db_session
from app.domain.enums import CapabilityType
from app.domain.permissions import PermissionCode


router = APIRouter()
service = CapabilityService()
model_provider_service = ModelProviderService()


@router.get(
    "",
    response_model=list[CapabilityRead],
    dependencies=[Depends(require_permission(PermissionCode.CAPABILITIES_READ))],
)
async def list_capabilities(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    capability_type: Annotated[CapabilityType | None, Query(alias="type")] = None,
) -> list[CapabilityRead]:
    return await service.list(session, capability_type)


@router.post(
    "",
    response_model=CapabilityRead,
    dependencies=[Depends(require_permission(PermissionCode.CAPABILITIES_CREATE))],
)
async def create_capability(
    payload: CapabilityCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CapabilityRead:
    try:
        return await service.create(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/model-providers/check",
    response_model=ModelProviderCheckResponse,
    dependencies=[Depends(require_permission(PermissionCode.CAPABILITIES_READ))],
)
async def check_model_provider(
    payload: ModelProviderProbeRequest,
) -> ModelProviderCheckResponse:
    try:
        return model_provider_service.check(payload)
    except UnsupportedModelProviderModeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/model-providers/discover-models",
    response_model=ModelProviderDiscoverResponse,
    dependencies=[Depends(require_permission(PermissionCode.CAPABILITIES_READ))],
)
async def discover_model_provider_models(
    payload: ModelProviderProbeRequest,
) -> ModelProviderDiscoverResponse:
    try:
        return model_provider_service.discover_models(payload)
    except UnsupportedModelProviderModeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{capability_id}",
    response_model=CapabilityRead,
    dependencies=[Depends(require_permission(PermissionCode.CAPABILITIES_READ))],
)
async def get_capability(
    capability_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CapabilityRead:
    try:
        return await service.get(session, capability_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/{capability_id}",
    response_model=CapabilityRead,
    dependencies=[Depends(require_permission(PermissionCode.CAPABILITIES_UPDATE))],
)
async def update_capability(
    capability_id: str,
    payload: CapabilityUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CapabilityRead:
    try:
        return await service.update(session, capability_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/{capability_id}",
    response_model=CapabilityDeleteResponse,
    dependencies=[Depends(require_permission(PermissionCode.CAPABILITIES_DELETE))],
)
async def delete_capability(
    capability_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CapabilityDeleteResponse:
    try:
        return await service.delete(session, capability_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
