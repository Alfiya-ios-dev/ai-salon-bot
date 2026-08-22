from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import SalesPromptResponse, SalesPromptUpdate
from app.services.sales_prompt_service import get_or_create_sales_prompt

router = APIRouter()


@router.get("", response_model=SalesPromptResponse)
async def get_prompts(db: AsyncSession = Depends(get_db)):
    return await get_or_create_sales_prompt(db)


@router.put("", response_model=SalesPromptResponse)
async def update_prompts(payload: SalesPromptUpdate, db: AsyncSession = Depends(get_db)):
    prompt = await get_or_create_sales_prompt(db)
    prompt.system_prompt = payload.system_prompt
    prompt.upsell_scripts = payload.upsell_scripts
    prompt.objection_handling = payload.objection_handling
    await db.commit()
    await db.refresh(prompt)
    return prompt
