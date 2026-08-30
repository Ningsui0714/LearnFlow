from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.plugin import PluginRelease
from app.services.architecture_registry import (
    plugin_registry_projection,
    registry_manifest,
    registry_validation_report,
)


router = APIRouter(prefix="/architecture", tags=["Architecture Authority"])


@router.get("/registry")
async def get_architecture_registry(db: AsyncSession = Depends(get_db)):
    manifest = registry_manifest()
    releases = list((await db.execute(select(PluginRelease).order_by(
        PluginRelease.plugin_id,
        PluginRelease.imported_at,
    ))).scalars().all())
    manifest["dynamic_plugin_releases"] = [
        {
            **plugin_registry_projection(row.manifest or {}),
            "release_id": row.id,
            "root_hash": row.root_hash,
            "trust_state": row.trust_state,
            "status": row.status,
        }
        for row in releases
    ]
    return manifest


@router.get("/validate")
async def validate_architecture_registry():
    return registry_validation_report()
