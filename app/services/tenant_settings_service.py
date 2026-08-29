from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessInfo
from app.schemas import TenantSettingsResponse, TenantSettingsUpdate

# Beauty-salon wording stays the default so every tenant created before this
# feature existed keeps behaving exactly as before with zero migration.
TENANT_SETTINGS_DEFAULTS: dict[str, str] = {
    "industry_type": "beauty",
    "staff_label_singular": "Мастер",
    "staff_label_plural": "Мастера",
    "service_label": "Услуга",
}


async def get_tenant_settings(db: AsyncSession) -> TenantSettingsResponse:
    """Resolves the tenant-profile settings from BusinessInfo rows (the same
    generic key/value table used for name/address/working_hours — no
    separate table needed), falling back to TENANT_SETTINGS_DEFAULTS for
    any key this tenant hasn't explicitly set.
    """
    result = await db.execute(
        select(BusinessInfo).where(BusinessInfo.key.in_(TENANT_SETTINGS_DEFAULTS.keys()))
    )
    stored = {row.key: row.value for row in result.scalars().all()}
    values = {key: stored.get(key, default) for key, default in TENANT_SETTINGS_DEFAULTS.items()}
    return TenantSettingsResponse(**values)


def is_default_tenant_settings(settings: TenantSettingsResponse) -> bool:
    """True if every field is still at its beauty-salon default — lets
    prompt assembly skip the terminology instruction entirely for the
    common case instead of spending tokens restating the default wording.
    """
    return all(getattr(settings, key) == default for key, default in TENANT_SETTINGS_DEFAULTS.items())


async def update_tenant_settings(db: AsyncSession, payload: TenantSettingsUpdate) -> TenantSettingsResponse:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in updates.items():
        row = await db.get(BusinessInfo, key)
        if row is None:
            db.add(BusinessInfo(key=key, value=value))
        else:
            row.value = value
    await db.commit()
    return await get_tenant_settings(db)
