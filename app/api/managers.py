from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_dependencies import get_current_tenant_db
from app.models import Manager
from app.schemas import ManagerCreate, ManagerResponse

router = APIRouter()


def _to_manager_response(manager: Manager) -> ManagerResponse:
    return ManagerResponse(
        id=manager.id,
        name=manager.manager_name,
        phone=manager.notification_phone,
        is_senior=manager.is_senior,
    )


@router.get("", response_model=list[ManagerResponse])
async def list_managers(db: AsyncSession = Depends(get_current_tenant_db)):
    result = await db.execute(select(Manager).order_by(Manager.id))
    return [_to_manager_response(m) for m in result.scalars().all()]


@router.post("", response_model=ManagerResponse, status_code=201)
async def create_manager(payload: ManagerCreate, db: AsyncSession = Depends(get_current_tenant_db)):
    manager = Manager(
        manager_name=payload.name,
        notification_phone=payload.phone,
        is_senior=payload.is_senior,
    )
    db.add(manager)
    await db.commit()
    await db.refresh(manager)
    return _to_manager_response(manager)


@router.delete("/{manager_id}", status_code=204)
async def delete_manager(manager_id: int, db: AsyncSession = Depends(get_current_tenant_db)):
    manager = await db.get(Manager, manager_id)
    if manager is None:
        raise HTTPException(status_code=404, detail="Manager not found")
    await db.delete(manager)
    await db.commit()
