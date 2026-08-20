from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


PERFORMANCE_INPUT_MAX_AGE_HOURS = 24


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _retention_at_or_after(rows: Any, ratio: float) -> float | None:
    """Return the first available audience-retention point at a normalized time."""
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        elapsed = _number(row.get("elapsedVideoTimeRatio"))
        retained = _number(row.get("audienceWatchRatio"))
        if elapsed is not None and retained is not None and elapsed >= ratio:
            return retained
    return None


def _performance_input_freshness(generated_at: Any, now: datetime | None = None) -> dict[str, Any]:
    """Describe analytics-export freshness without rejecting otherwise usable input."""
    value = str(generated_at or "").strip()
    if not value:
        return {"status": "unavailable", "generated_at": None, "age_hours": None}
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return {"status": "invalid", "generated_at": value, "age_hours": None}
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (reference - timestamp.astimezone(timezone.utc)).total_seconds() / 3600)
    return {
        "status": "stale" if age_hours > PERFORMANCE_INPUT_MAX_AGE_HOURS else "fresh",
        "generated_at": value,
        "age_hours": round(age_hours, 1),
        "max_age_hours": PERFORMANCE_INPUT_MAX_AGE_HOURS,
    }


def build_channel_snapshot(raw_data: str) -> dict[str, Any]:
    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError:
        return {
            "source_format": "text",
            "raw_summary": raw_data[:12000],
            "video_count": 0,
            "recent_videos": [],
            "data_quality": ["Input không phải JSON; performance fields bị giới hạn."],
        }
    freshness = _performance_input_freshness(data.get("generated_at"))
    data_quality: list[str] = []
    if freshness["status"] == "stale":
        data_quality.append(
            "STALE_PERFORMANCE_INPUT: snapshot analytics đã %.1f giờ (mốc cảnh báo: %d giờ)."
            % (freshness["age_hours"], PERFORMANCE_INPUT_MAX_AGE_HOURS)
        )
    elif freshness["status"] == "invalid":
        data_quality.append("PERFORMANCE_INPUT_TIMESTAMP_INVALID: generated_at không đọc được.")

    videos_value = data.get("videos", {}) if isinstance(data, dict) else {}
    if isinstance(videos_value, dict):
        video_rows = list(videos_value.values())
    elif isinstance(videos_value, list):
        video_rows = videos_value
    else:
        video_rows = []
    recent_videos = []
    for video in video_rows:
        if not isinstance(video, dict):
            continue
        summary_rows = ((video.get("analytics") or {}).get("summary") or [])
        analytics = summary_rows[0] if summary_rows and isinstance(summary_rows[0], dict) else {}
        all_analytics = video.get("analytics") or {}
        reach = all_analytics.get("reach") if isinstance(all_analytics.get("reach"), dict) else {}
        impressions = _number(reach.get("impressions"))
        reach_ctr = _number(reach.get("impressions_ctr"))
        retention = all_analytics.get("retention") or []
        traffic_rows = all_analytics.get("traffic_source") or []
        traffic_sources = {
            str(row.get("insightTrafficSourceType")): row.get("views")
            for row in traffic_rows
            if isinstance(row, dict) and row.get("insightTrafficSourceType")
        }
        recent_videos.append(
            {
                "video_id": video.get("videoId"),
                "title": video.get("title"),
                "published_at": video.get("publishedAt"),
                "duration_iso": video.get("duration_iso"),
                "views": analytics.get("views", video.get("viewCount")),
                "average_view_duration_seconds": analytics.get("averageViewDuration"),
                "average_view_percentage": analytics.get("averageViewPercentage"),
                "likes": analytics.get("likes", video.get("likeCount")),
                "comments": analytics.get("comments", video.get("commentCount")),
                # The export's legacy ctr field is normally null. Reporting API
                # reach is the authoritative video-thumbnail CTR when present.
                "ctr": reach_ctr if reach_ctr is not None else _number(all_analytics.get("ctr")),
                "impressions": impressions,
                "intro_retention_10pct": _retention_at_or_after(retention, 0.10),
                "retention_30pct": _retention_at_or_after(retention, 0.30),
                "traffic_sources": traffic_sources,
            }
        )
    recent_videos.sort(key=lambda row: row.get("published_at") or "", reverse=True)
    return {
        "source_format": "youtube_data_v%d" % int(data.get("schema_version", 1)),
        "generated_at": data.get("generated_at"),
        "input_freshness": freshness,
        "channel_id": data.get("channel_id"),
        "analytics_window": data.get("analytics_window"),
        "video_count": len(recent_videos),
        "recent_videos": recent_videos,
        "recent_titles": [row["title"] for row in recent_videos if row.get("title")],
        "data_quality": data_quality,
    }


def build_performance_review(snapshot: dict[str, Any]) -> dict[str, Any]:
    videos = snapshot.get("recent_videos", [])
    eligible = [row for row in videos if isinstance(row.get("views"), (int, float)) and row["views"] >= 30]
    best = max(
        eligible,
        key=lambda row: row.get("average_view_percentage") or 0,
        default=None,
    )
    ctr_values = [row.get("ctr") for row in videos if isinstance(row.get("ctr"), (int, float))]
    reach_sample = [row for row in videos if (row.get("impressions") or 0) >= 1_000 and isinstance(row.get("ctr"), (int, float))]
    low_ctr_reach = [row for row in reach_sample if row["ctr"] < 0.035]
    weak_intro = [
        row for row in videos
        if isinstance(row.get("intro_retention_10pct"), (int, float)) and row["intro_retention_10pct"] < 0.30
    ]
    warnings = []
    freshness = snapshot.get("input_freshness") if isinstance(snapshot.get("input_freshness"), dict) else {}
    if freshness.get("status") == "stale":
        warnings.append(
            "STALE_PERFORMANCE_INPUT: analytics snapshot đã %.1f giờ; refresh youtube_data.json trước khi đổi packaging/topic."
            % float(freshness.get("age_hours") or 0)
        )
    elif freshness.get("status") == "invalid":
        warnings.append("PERFORMANCE_INPUT_TIMESTAMP_INVALID: generated_at không đọc được; không xác minh được độ mới analytics.")
    if not ctr_values:
        warnings.append("PACKAGING_UNKNOWN: thiếu analytics.reach.impressions_ctr từ Reporting API.")
    insufficient = [row.get("video_id") for row in videos if (row.get("views") or 0) < 30]
    if insufficient:
        warnings.append("INSUFFICIENT_DATA: %s" % ", ".join(str(value) for value in insufficient))
    if low_ctr_reach and weak_intro:
        primary_bottleneck = "PACKAGING_AND_HOOK_MISMATCH"
        hypothesis = "Giữ title một pain cụ thể, thumbnail một contradiction 4-8 ký tự, rồi trả đúng promise đó trong 20 giây đầu trước khi mở mechanism."
    elif low_ctr_reach:
        primary_bottleneck = "PACKAGING_CTR_LOW"
        hypothesis = "Test một title pain-first ngắn hơn và thumbnail chỉ một visual conflict + 4-8 ký tự; không đổi script chỉ để sửa CTR."
    elif weak_intro:
        primary_bottleneck = "EARLY_RETENTION"
        hypothesis = "Giữ packaging đang hiệu quả; rút cold open về behavior + contradiction + core question trước mechanism."
    else:
        primary_bottleneck = "NO_CLEAR_BOTTLENECK"
        hypothesis = "Tiếp tục thử một topic/promise hẹp và theo dõi CTR cùng retention trước khi thay đổi nhiều biến cùng lúc."
    diagnostics = []
    for row in reach_sample:
        diagnostics.append({
            "video_id": row.get("video_id"),
            "title": row.get("title"),
            "impressions": int(row.get("impressions") or 0),
            "ctr_pct": round(float(row.get("ctr") or 0) * 100, 2),
            "intro_retention_10pct_pct": round(float(row["intro_retention_10pct"]) * 100, 2) if isinstance(row.get("intro_retention_10pct"), (int, float)) else None,
            "diagnosis": "PACKAGING_AND_HOOK" if row in low_ctr_reach and row in weak_intro else ("PACKAGING" if row in low_ctr_reach else "OBSERVE"),
        })
    return {
        "sample_quality": "LOW_SAMPLE" if len(eligible) < 3 else "LIMITED",
        "strongest_signal": (
            "Video %s có AVP cao nhất trong sample đủ 30 views." % best.get("video_id")
            if best
            else "Chưa có sample đủ mạnh."
        ),
        "primary_bottleneck": primary_bottleneck,
        "secondary_bottleneck": "EARLY_RETENTION" if weak_intro else "NONE_CONFIRMED",
        "what_worked": [
            "Góc 『嫌われる勇気』/課題の分離 có AVP nội bộ tốt nhất."
        ] if best and "嫌われる勇気" in (best.get("title") or "") else [],
        "what_failed": [
            "Video có reach cao nhưng CTR thấp: ưu tiên sửa packaging trước khi đổi topic."
        ] if low_ctr_reach else (["Intro retention thấp: packaging hứa điều script chưa trả đủ sớm."] if weak_intro else []),
        "confidence": "low-to-medium",
        "test_one_hypothesis": hypothesis,
        "next_format": {"duration_mode": "flexible", "target_minutes": "6-12"},
        "input_freshness": freshness,
        "warnings": warnings,
        "best_internal_video": best,
        "packaging_diagnostics": diagnostics,
    }
