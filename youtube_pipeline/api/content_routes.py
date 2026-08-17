"""API cho nội dung content/ — queue video, nhật ký dùng, thư viện cơ chế/frame.

Đọc/ghi qua content_manager (fail-silent với pipeline). Nhưng API cần biết kết
quả thật để trả mã lỗi đúng, nên route kiểm tra trước bằng find_queue_entry
rồi mới gọi hàm ghi — tránh lỗi 404/409 mơ hồ khi hàm ghi trả None.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from youtube_pipeline import content_manager

router = APIRouter(prefix="/api/content")


def _topic_of(body: dict) -> str:
    topic = (body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic không được rỗng")
    return topic


def _require_entry(topic: str) -> dict:
    entry = content_manager.find_queue_entry(topic)
    if entry is None:
        raise HTTPException(status_code=404, detail="Topic không khớp queue: %s" % topic)
    return entry


# ------------------------------------------------------------------ read


@router.get("/queue")
def queue() -> dict:
    return {
        "topics": content_manager.queue_overview(),
        "diary": content_manager.diary_entries(),
        "recent_mechanisms": content_manager.recently_used_mechanisms(),
    }


@router.get("/mechanisms")
def mechanisms() -> dict:
    return {"mechanisms": content_manager.load_mechanisms()}


@router.get("/cultural-frames")
def cultural_frames() -> dict:
    return {"frames": content_manager.load_cultural_frames()}


# ----------------------------------------------------------------- write


@router.post("/queue/in-progress")
def queue_in_progress(body: dict) -> dict:
    """A3 — chuyển status queued → in_progress (idempotent)."""
    topic = _topic_of(body)
    entry = _require_entry(topic)
    if entry["status"] == "in_progress":
        return {"queue_no": entry["queue_no"], "status": "in_progress", "changed": False}
    if entry["status"] == "published":
        raise HTTPException(
            status_code=409, detail="Topic #%d đã published" % entry["queue_no"]
        )
    queue_no = content_manager.mark_topic_in_progress(topic)
    if queue_no is None:
        raise HTTPException(status_code=409, detail="Không cập nhật được — thử lại sau")
    return {"queue_no": queue_no, "status": "in_progress", "changed": True}


@router.post("/queue/publish")
def queue_publish(body: dict) -> dict:
    """E1/E2 — ghi Nhật ký dùng (mechanism + frame) và status → published.

    video_id chưa có ở thời điểm này (upload là bước thủ công) — điền sau
    bằng POST /queue/video-id.
    """
    topic = _topic_of(body)
    entry = _require_entry(topic)
    if entry["status"] == "published":
        raise HTTPException(
            status_code=409,
            detail="Topic #%d đã published — dùng /queue/video-id để điền ID"
            % entry["queue_no"],
        )
    queue_no = content_manager.mark_topic_published(
        topic,
        video_id="",
        mechanism=(body.get("mechanism") or "").strip(),
        frame=(body.get("frame") or "").strip(),
    )
    if queue_no is None:
        raise HTTPException(status_code=409, detail="Không cập nhật được — thử lại sau")
    return {"queue_no": queue_no, "status": "published", "changed": True}


@router.post("/queue/video-id")
def queue_video_id(body: dict) -> dict:
    """Điền video_id thật vào dòng nhật ký mới nhất của topic (sau khi đăng)."""
    topic = _topic_of(body)
    video_id = (body.get("video_id") or "").strip()
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id không được rỗng")
    entry = _require_entry(topic)
    queue_no = content_manager.set_diary_video_id(topic, video_id)
    if queue_no is None:
        raise HTTPException(
            status_code=409,
            detail="Chưa có dòng nhật ký cho #%d — publish trước"
            % entry["queue_no"],
        )
    return {"queue_no": queue_no, "video_id": video_id, "changed": True}
