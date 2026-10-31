from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
INSIGHTS_PATH = BASE_DIR.parent.parent / "FrameBurn" / "frameburn_platform" / "config" / "short_video_site_insights.json"


@dataclass
class DemoTask:
    task_id: str
    prompt: str
    quality: str
    duration: int
    mode: str
    with_audio: bool
    provider: str
    created_at: str
    created_ts: float
    is_deleted: bool = False


app = FastAPI(title="FrameBurn Frontend Preview", version="0.1.0")

_TASKS: dict[str, DemoTask] = {}
_MONTHLY_QUOTA = 100_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_status(task: DemoTask) -> str:
    elapsed = time.time() - task.created_ts
    if elapsed < 1.5:
        return "queued"
    if elapsed < 4.5:
        return "running"
    return "completed"


def _estimate_credits(quality: str, duration: int, with_audio: bool) -> int:
    quality_factor = {"480p": 1.0, "720p": 1.5, "1080p": 2.2, "2k": 2.8}.get(quality, 1.0)
    duration_factor = max(1.0, duration / 3)
    audio_factor = 1.2 if with_audio else 1.0
    return int(round(60 * quality_factor * duration_factor * audio_factor))


def _serialize_task(task: DemoTask) -> dict[str, Any]:
    status = _task_status(task)
    estimate_credits = _estimate_credits(task.quality, task.duration, task.with_audio)
    credits_used = estimate_credits if status == "completed" else 0
    credits_remaining = max(_MONTHLY_QUOTA - credits_used, 0)

    if status == "completed":
        segment_status = "ok"
    elif status == "running":
        segment_status = "running"
    else:
        segment_status = "queued"

    return {
        "task_id": task.task_id,
        "status": status,
        "content_type": "video",
        "quality": task.quality,
        "duration": task.duration,
        "mode": task.mode,
        "with_audio": task.with_audio,
        "provider": task.provider,
        "created_at": task.created_at,
        "updated_at": _now_iso(),
        "error": None,
        "cdn_url": None,
        "estimate_credits": estimate_credits,
        "usage": {
            "credits_used": credits_used,
            "monthly_quota": _MONTHLY_QUOTA,
            "usage_percent": int(round((credits_used / _MONTHLY_QUOTA) * 100)),
            "credits_remaining": credits_remaining,
            "remaining_percent": int(round((credits_remaining / _MONTHLY_QUOTA) * 100)),
        },
        "segments": [
            {
                "seq": 1,
                "status": segment_status,
                "duration_sec": task.duration,
                "credits_used": credits_used,
                "text": task.prompt,
            }
        ],
        "download_url": f"/api/v1/tasks/{task.task_id}/download",
        "video_url": None,
        "is_deleted": task.is_deleted,
        "deleted_at": _now_iso() if task.is_deleted else None,
    }


def _load_insights() -> dict[str, Any]:
    if not INSIGHTS_PATH.exists():
        return {
            "updated_at": _now_iso(),
            "sources": [],
            "design_patterns": {},
            "frameburn_recommendations": [],
            "prompt_templates": [],
            "count": {"sources": 0, "recommendations": 0, "prompt_templates": 0},
        }

    with INSIGHTS_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    sources = payload.get("sources", [])
    recommendations = payload.get("frameburn_recommendations", [])
    templates = payload.get("prompt_templates", [])
    return {
        "updated_at": payload.get("updated_at"),
        "sources": sources,
        "design_patterns": payload.get("design_patterns", {}),
        "frameburn_recommendations": recommendations,
        "prompt_templates": templates,
        "count": {
            "sources": len(sources),
            "recommendations": len(recommendations),
            "prompt_templates": len(templates),
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "FrameBurn Frontend Preview",
        "default_provider": "local",
        "monthly_quota_credits": _MONTHLY_QUOTA,
    }


@app.get("/api/v1/versions")
def versions() -> dict[str, Any]:
    return {
        "qualities": [
            {"id": "480p", "label": "Basic 480P", "base_price": 0.22, "min_duration_sec": 3, "max_duration_sec": 30},
            {"id": "720p", "label": "Pro 720P", "base_price": 0.33, "min_duration_sec": 3, "max_duration_sec": 30},
            {"id": "1080p", "label": "Ultra 1080P", "base_price": 0.49, "min_duration_sec": 5, "max_duration_sec": 30},
        ],
        "providers": [
            {"id": "local", "label": "Local generator (default, no external token)"},
            {"id": "volc", "label": "Volc Ark API (consumes external token)"},
        ],
    }


@app.get("/api/v1/functions")
def functions() -> dict[str, Any]:
    return {
        "items": [
            {
                "id": "video",
                "label": "AI 视频生成",
                "enabled": True,
                "provider": "local",
                "formats": ["480p", "720p", "1080p"],
                "price_cents": {"tier1": 22},
                "price_factor": {"min": 1.0, "max": 2.2},
                "avg_gen_seconds": 3,
            }
        ],
        "count": 1,
    }


@app.get("/api/v1/insights/short-video-sites")
def insights() -> dict[str, Any]:
    return _load_insights()


@app.post("/api/v1/tasks")
async def create_task(
    prompt: str = Form(...),
    quality: str = Form("480p"),
    duration: int = Form(3),
    mode: str = Form("text"),
    with_audio: bool = Form(False),
    provider: str = Form("local"),
    video: UploadFile | None = File(default=None),
) -> JSONResponse:
    cleaned_prompt = (prompt or "").strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=400, detail={"code": "PARAM_INVALID", "message": "Prompt cannot be empty"})

    normalized_mode = (mode or "text").strip().lower()
    has_video = video is not None and bool(getattr(video, "filename", None))
    if normalized_mode == "video" and not has_video:
        raise HTTPException(status_code=400, detail={"code": "PARAM_INVALID", "message": "Video mode requires a reference MP4 file"})

    task_id = str(uuid.uuid4())
    record = DemoTask(
        task_id=task_id,
        prompt=cleaned_prompt,
        quality=quality,
        duration=max(3, min(30, int(duration))),
        mode=normalized_mode,
        with_audio=with_audio,
        provider=(provider or "local").strip().lower(),
        created_at=_now_iso(),
        created_ts=time.time(),
    )
    _TASKS[task_id] = record

    payload = _serialize_task(record)
    payload.update({"message": "Task accepted", "poll_url": f"/api/v1/tasks/{task_id}"})
    return JSONResponse(payload, status_code=202)


@app.get("/api/v1/tasks")
def list_tasks() -> dict[str, Any]:
    items = [_serialize_task(task) for task in _TASKS.values()]
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {"items": items, "count": len(items)}


@app.get("/api/v1/tasks/{task_id}")
def task_detail(task_id: str) -> dict[str, Any]:
    task = _TASKS.get(task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Task not found"})
    return _serialize_task(task)


@app.delete("/api/v1/tasks/{task_id}")
def delete_task(task_id: str) -> dict[str, Any]:
    task = _TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Task not found"})
    task.is_deleted = True
    return {"task_id": task_id, "status": "deleted"}


@app.get("/api/v1/tasks/{task_id}/download")
def download(task_id: str) -> dict[str, Any]:
    task = _TASKS.get(task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Task not found"})

    payload = _serialize_task(task)
    if payload["status"] != "completed":
        raise HTTPException(status_code=400, detail={"code": "PARAM_INVALID", "message": "Task is not completed yet"})

    return {
        "task_id": task_id,
        "cdn_url": None,
        "cdn_expires_at": None,
        "local_fallback_url": None,
        "expires_in_sec": None,
    }


app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="preview-static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8787)
