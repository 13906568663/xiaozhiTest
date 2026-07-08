"""技能 REST API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_current_user, require_permission
from app.db.session import get_db_session
from app.domain.permissions import PermissionCode
from app.iam.schemas import UserRead
from app.skill.schemas import (
    SkillCreate,
    SkillDeleteResponse,
    SkillListItem,
    SkillListResponse,
    SkillRead,
    SkillUpdate,
)
from app.skill.services import skills as skill_service
from app.skill.services.skills import SkillSourceError

router = APIRouter()


@router.get(
    "",
    response_model=SkillListResponse,
    dependencies=[Depends(require_permission(PermissionCode.SKILLS_READ))],
)
async def list_skills(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    code: Annotated[str | None, Query(description="按编码模糊筛选")] = None,
    status: Annotated[str | None, Query(description="按状态精确筛选 active/inactive")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 20,
) -> SkillListResponse:
    items, total = await skill_service.list_skills(
        session,
        code=code,
        status=status,
        page=page,
        page_size=page_size,
    )
    return SkillListResponse(
        items=[SkillListItem.model_validate(s) for s in items],
        total=total,
    )


@router.post(
    "",
    response_model=SkillRead,
    dependencies=[Depends(require_permission(PermissionCode.SKILLS_WRITE))],
)
async def create_skill(
    payload: SkillCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[UserRead, Depends(require_current_user)],
) -> SkillRead:
    try:
        skill = await skill_service.create_skill(
            session,
            source=payload.source,
            status=payload.status,
            created_by=current_user.username,
        )
    except SkillSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(skill)
    return SkillRead.model_validate(skill)


@router.get(
    "/{skill_id}",
    response_model=SkillRead,
    dependencies=[Depends(require_permission(PermissionCode.SKILLS_READ))],
)
async def get_skill(
    skill_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SkillRead:
    skill = await skill_service.get_skill(session, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    return SkillRead.model_validate(skill)


@router.put(
    "/{skill_id}",
    response_model=SkillRead,
    dependencies=[Depends(require_permission(PermissionCode.SKILLS_WRITE))],
)
async def update_skill(
    skill_id: str,
    payload: SkillUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SkillRead:
    try:
        skill = await skill_service.update_skill(
            session,
            skill_id,
            source=payload.source,
            status=payload.status,
        )
    except SkillSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    await session.commit()
    await session.refresh(skill)
    return SkillRead.model_validate(skill)


@router.delete(
    "/{skill_id}",
    response_model=SkillDeleteResponse,
    dependencies=[Depends(require_permission(PermissionCode.SKILLS_WRITE))],
)
async def delete_skill(
    skill_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SkillDeleteResponse:
    deleted = await skill_service.delete_skill(session, skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="技能不存在")
    await session.commit()
    return SkillDeleteResponse(deleted=True, skill_id=skill_id)
