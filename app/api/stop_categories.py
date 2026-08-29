from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_dependencies import get_current_tenant_db
from app.models import StopCategory
from app.schemas import StopCategoryCreate, StopCategoryResponse

router = APIRouter()


@router.get("", response_model=list[StopCategoryResponse])
async def list_stop_categories(db: AsyncSession = Depends(get_current_tenant_db)):
    result = await db.execute(select(StopCategory).order_by(StopCategory.id))
    return result.scalars().all()


@router.post("", response_model=StopCategoryResponse, status_code=201)
async def create_stop_category(
    payload: StopCategoryCreate, db: AsyncSession = Depends(get_current_tenant_db)
):
    category = StopCategory(**payload.model_dump())
    db.add(category)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Stop category '{payload.name}' already exists")
    await db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=204)
async def delete_stop_category(category_id: int, db: AsyncSession = Depends(get_current_tenant_db)):
    category = await db.get(StopCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Stop category not found")
    await db.delete(category)
    await db.commit()
