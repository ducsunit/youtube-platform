from __future__ import annotations

import json
from typing import Any


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
                "ctr": (video.get("analytics") or {}).get("ctr"),
            }
        )
    recent_videos.sort(key=lambda row: row.get("published_at") or "", reverse=True)
    return {
        "source_format": "youtube_data_v%d" % int(data.get("schema_version", 1)),
        "generated_at": data.get("generated_at"),
        "channel_id": data.get("channel_id"),
        "analytics_window": data.get("analytics_window"),
        "video_count": len(recent_videos),
        "recent_videos": recent_videos,
        "recent_titles": [row["title"] for row in recent_videos if row.get("title")],
        "data_quality": [],
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
    warnings = []
    if not ctr_values:
        warnings.append("PACKAGING_UNKNOWN: youtube_data.json không có CTR thật.")
    insufficient = [row.get("video_id") for row in videos if (row.get("views") or 0) < 30]
    if insufficient:
        warnings.append("INSUFFICIENT_DATA: %s" % ", ".join(str(value) for value in insufficient))
    return {
        "sample_quality": "LOW_SAMPLE" if len(eligible) < 3 else "LIMITED",
        "strongest_signal": (
            "Video %s có AVP cao nhất trong sample đủ 30 views." % best.get("video_id")
            if best
            else "Chưa có sample đủ mạnh."
        ),
        "primary_bottleneck": "PACKAGING_UNKNOWN" if not ctr_values else "REVIEW_REQUIRED",
        "secondary_bottleneck": "EARLY_RETENTION",
        "what_worked": [
            "Góc 『嫌われる勇気』/課題の分離 có AVP nội bộ tốt nhất."
        ] if best and "嫌われる勇気" in (best.get("title") or "") else [],
        "what_failed": ["Video 25-26 phút có AVP thấp."],
        "confidence": "low-to-medium",
        "test_one_hypothesis": "Resource 9-11 phút với title/thumbnail tình huống cụ thể giúp giảm rơi sớm.",
        "next_format": {"duration_mode": "focus", "target_minutes": "9-11"},
        "warnings": warnings,
        "best_internal_video": best,
    }
