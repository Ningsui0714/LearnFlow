"""
Settings API: read/write .env config, test connections.
"""
import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")


class SettingsUpdate(BaseModel):
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    embedding_backend: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_api_key: Optional[str] = None
    embedding_base_url: Optional[str] = None


def _read_env() -> dict:
    """Read .env file into dict."""
    config = {}
    if not os.path.exists(ENV_PATH):
        return config
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                config[key.strip()] = val.strip()
    return config


def _write_env(updates: dict):
    """Write updates to .env, preserving existing keys and order."""
    existing = _read_env()
    existing.update(updates)

    seen_keys = set(updates.keys())
    lines = []

    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    lines.append(line)
                else:
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        lines.append(f"{key}={updates[key]}\n")
                        seen_keys.discard(key)
                    else:
                        lines.append(line)

    # Append new keys not already in file
    for key in seen_keys:
        lines.append(f"{key}={updates[key]}\n")

    with open(ENV_PATH, "w") as f:
        f.writelines(lines)


def _mask_key(key: str) -> str:
    """Mask API key for display — show first 8 + last 4 chars."""
    if not key or len(key) < 12:
        return "***"
    return key[:8] + "…" + key[-4:]


# ── Routes ──


@router.get("/settings")
async def get_settings():
    """Get current settings with masked API keys."""
    from app.core.config import settings as app_settings

    raw = _read_env()

    emb_key = raw.get("EMBEDDING_API_KEY", "") or app_settings.embedding_api_key or ""

    return {
        "llm_api_key": _mask_key(raw.get("LLM_API_KEY", app_settings.llm_api_key)),
        "llm_base_url": raw.get("LLM_BASE_URL", app_settings.llm_base_url),
        "llm_model": raw.get("LLM_MODEL", app_settings.llm_model),
        "embedding_backend": raw.get("EMBEDDING_BACKEND", app_settings.embedding_backend),
        "embedding_model": raw.get("EMBEDDING_MODEL", app_settings.embedding_model),
        "embedding_api_key": _mask_key(emb_key) if emb_key else "",
        "embedding_base_url": raw.get("EMBEDDING_BASE_URL", app_settings.embedding_base_url or ""),
        "has_key": bool(app_settings.llm_api_key and app_settings.llm_api_key not in ("", "sk-your-key-here")),
    }


class TestConnectionRequest(BaseModel):
    api_key: str
    base_url: str
    model: str


@router.post("/settings/test")
async def test_connection(req: TestConnectionRequest):
    """Test LLM connection with provided credentials."""
    from openai import AsyncOpenAI

    try:
        client = AsyncOpenAI(api_key=req.api_key, base_url=req.base_url)
        resp = await client.chat.completions.create(
            model=req.model,
            messages=[{"role": "user", "content": "say just: OK"}],
            max_tokens=10,
            timeout=15,
        )
        msg = resp.choices[0].message.content
        return {"status": "ok", "message": msg or "(empty response)", "model": resp.model}
    except Exception as e:
        error_str = str(e)
        if "401" in error_str or "Unauthorized" in error_str or "Authentication" in error_str:
            raise HTTPException(400, "认证失败：API Key 无效")
        elif "404" in error_str:
            raise HTTPException(400, f"模型不存在：{req.model}，请检查模型名称")
        elif "timeout" in error_str.lower() or "timed out" in error_str.lower():
            raise HTTPException(400, "连接超时：请检查 Base URL 是否正确")
        else:
            raise HTTPException(400, f"连接失败：{error_str[:200]}")


@router.post("/settings/test-embedding")
async def test_embedding(req: TestConnectionRequest):
    """Test embedding API connection."""
    from openai import AsyncOpenAI

    try:
        client = AsyncOpenAI(api_key=req.api_key, base_url=req.base_url)
        resp = await client.embeddings.create(
            model=req.model or "text-embedding-ada-002",
            input="test",
            timeout=15,
        )
        dims = len(resp.data[0].embedding)
        return {"status": "ok", "dimensions": dims}
    except Exception as e:
        error_str = str(e)
        if "404" in error_str:
            raise HTTPException(400, "Embedding 端点不可用：该 API 可能不支持 embedding，建议使用 local 后端")
        else:
            raise HTTPException(400, f"测试失败：{error_str[:200]}")


@router.put("/settings")
async def save_settings(data: SettingsUpdate):
    """Save settings to .env file."""
    updates = {}
    # Only include non-None values
    mapping = {
        "llm_api_key": "LLM_API_KEY",
        "llm_base_url": "LLM_BASE_URL",
        "llm_model": "LLM_MODEL",
        "embedding_backend": "EMBEDDING_BACKEND",
        "embedding_model": "EMBEDDING_MODEL",
        "embedding_api_key": "EMBEDDING_API_KEY",
        "embedding_base_url": "EMBEDDING_BASE_URL",
    }
    for field, env_key in mapping.items():
        val = getattr(data, field, None)
        if val is not None:
            updates[env_key] = val

    if not updates:
        raise HTTPException(400, "No settings to update")

    _write_env(updates)
    return {"status": "ok", "updated": list(updates.keys())}
