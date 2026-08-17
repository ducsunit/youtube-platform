#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
youtube_pull.py — Lấy dữ liệu phân tích cho các video kênh しずくの部屋.

Gọi 3 API của Google:
  1. YouTube Data API v3       -> metadata, stats, comments + replies
  2. YouTube Analytics API v2  -> retention, watch time, traffic và audience
  3. YouTube Reporting API v1  -> impressions, CTR và bulk reports theo ngày

Xuất ra 1 file JSON gọn (mặc định youtube_data.json) để gửi cho Claude phân tích.

------------------------------------------------------------------
CÁCH DÙNG NHANH
------------------------------------------------------------------
1. Cài thư viện (chạy 1 lần):
     pip install -r requirements.txt

2. Có file client_secret.json (OAuth Desktop app) tại project root.
   Xem README_youtube_setup.md để biết cách tạo.

3. Chạy:
     python -m youtube_pipeline.analysis.youtube_pull
   Sau đó chọn chức năng trong menu.

   Hoặc dùng CLI trực tiếp:
     python -m youtube_pipeline.analysis.youtube_pull --videos VIDEO_ID_1 VIDEO_ID_2

   Lần đầu sẽ mở trình duyệt để đăng nhập Google (tài khoản sở hữu kênh).
   Token được lưu vào token.json để các lần sau không phải đăng nhập lại.

Ví dụ:
     python -m youtube_pipeline.analysis.youtube_pull --videos dQw4w9WgXcQ abcd1234EFG --out video12_data.json

4. Lấy impressions/CTR:
     python -m youtube_pipeline.analysis.youtube_pull --setup-reporting
   Chờ report sẵn sàng rồi:
     python -m youtube_pipeline.analysis.youtube_pull --sync-reporting --out video12_data.json
------------------------------------------------------------------
LƯU Ý BẢO MẬT: KHÔNG gửi client_secret.json hay token.json cho ai.
Chỉ gửi file JSON output (không chứa credential).
------------------------------------------------------------------
"""

import argparse
import csv
import datetime as dt
import http.server
import io
import json
import os
import sys
import tempfile
import urllib.parse
import webbrowser

# ---- Nạp biến từ file .env (nếu có) -------------------------------------
# Đặt trước khi đọc os.getenv để các giá trị trong .env có hiệu lực.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # Không có python-dotenv cũng không sao: vẫn đọc được biến môi trường thật.
    pass

# ---- Google client libs -------------------------------------------------
try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials
    GOOGLE_API_AVAILABLE = True
except ImportError:  # Keep the module importable for tests and CLI help.
    build = None
    HttpError = Exception
    InstalledAppFlow = None
    AuthorizedSession = None
    Request = None
    Credentials = None
    GOOGLE_API_AVAILABLE = False

def _require_google_api() -> None:
    if not GOOGLE_API_AVAILABLE:
        raise RuntimeError(
            "Thiếu Google API dependencies. Chạy: pip install -e ."
        )

# Scope cần dùng:
#   - youtube.readonly     : đọc stats/kênh (Data API)
#   - yt-analytics.readonly: đọc báo cáo (Analytics API)
# Đổi scope thì PHẢI xoá token.json rồi đăng nhập lại để cấp lại quyền.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

# Reporting API sinh file CSV theo ngày. Reach reports (thêm từ 2026) là nguồn
# chính thức cho impressions + thumbnail CTR mà Analytics reports.query không có.
REPORT_TYPES = {
    "channel_reach_basic_a1": "Reach cơ bản (impressions + CTR theo video/ngày)",
    "channel_reach_combined_a1": "Reach theo traffic source + thiết bị",
    "channel_cards_a1": "Hiệu quả cards",
    "channel_end_screens_a1": "Hiệu quả end screens",
    "channel_subtitles_a3": "Lượt xem theo phụ đề",
    "audience_retention_a1": "Audience retention dạng bulk",
}
READ_RETRIES = 3

# Đường dẫn credential — có thể ghi đè qua .env (CLIENT_SECRET_FILE / TOKEN_FILE).
CLIENT_SECRET_FILE = os.getenv("CLIENT_SECRET_FILE", "client_secret.json")
TOKEN_FILE = os.getenv("TOKEN_FILE", "token.json")

# OAuth client cũng có thể lấy trực tiếp từ .env (khỏi cần client_secret.json).
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
PROJECT_ID = os.getenv("PROJECT_ID")  # tuỳ chọn, chỉ để ghi vào config cho đầy đủ.

# Loại OAuth client: "web" (Web application) hay "installed" (Desktop app).
# Web application BẮT BUỘC redirect URI khớp chính xác -> phải cố định port.
CLIENT_TYPE = os.getenv("CLIENT_TYPE", "installed").strip().lower()
# Redirect URI. Phải khớp CHÍNH XÁC (scheme, host, port, path, dấu / cuối)
# với một URI trong "Authorized redirect URIs" ở Google Cloud Console.
# Ví dụ: http://localhost:8000/api/v1/oauth/google/callback
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8765/")
# Port cố định cho local server. Mặc định lấy từ REDIRECT_URI.
_parsed_redirect = urllib.parse.urlparse(REDIRECT_URI)
OAUTH_PORT = int(os.getenv("OAUTH_PORT") or _parsed_redirect.port or 8765)


def _flow_from_env():
    """Dựng InstalledAppFlow từ CLIENT_ID/CLIENT_SECRET trong .env, hoặc None."""
    if not (CLIENT_ID and CLIENT_SECRET):
        return None
    # Key ngoài cùng phải khớp loại client ("web" hoặc "installed").
    key = "installed" if CLIENT_TYPE == "installed" else "web"
    inner = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": [REDIRECT_URI],
    }
    if PROJECT_ID:
        inner["project_id"] = PROJECT_ID
    return InstalledAppFlow.from_client_config({key: inner}, SCOPES)


def _run_flow(flow):
    """Chạy OAuth flow với redirect URI tùy chỉnh (kể cả path riêng).

    Thư viện google-auth-oauthlib chỉ hỗ trợ path "/" qua run_local_server,
    nên khi REDIRECT_URI có path khác (vd /api/v1/oauth/google/callback)
    ta tự dựng local server để bắt đúng path đó.
    """
    parsed = urllib.parse.urlparse(REDIRECT_URI)
    path = parsed.path or "/"

    # Path mặc định "/" -> dùng luôn helper của thư viện cho gọn.
    if path == "/":
        return flow.run_local_server(
            host=parsed.hostname or "localhost", port=OAUTH_PORT
        )

    # Path tùy chỉnh -> tự phục vụ 1 request để lấy authorization code.
    # localhost dùng http (không https), oauthlib mặc định từ chối -> bật cờ
    # cho phép insecure transport. An toàn vì chỉ chạy trên máy local.
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    flow.redirect_uri = REDIRECT_URI
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

    holder = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            holder["full"] = f"http://{parsed.hostname}:{OAUTH_PORT}{self.path}"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "Đăng nhập xong. Bạn có thể đóng tab này và quay lại terminal.".encode(
                    "utf-8"
                )
            )

        def log_message(self, *args):
            pass  # tắt log HTTP cho đỡ rối.

    server = http.server.HTTPServer((parsed.hostname or "localhost", OAUTH_PORT), _Handler)
    print("Mở trình duyệt để đăng nhập. Nếu không tự mở, dán URL này vào trình duyệt:")
    print(auth_url)
    webbrowser.open(auth_url)
    while "full" not in holder:
        server.handle_request()
    server.server_close()

    flow.fetch_token(authorization_response=holder["full"])
    return flow.credentials


# =========================================================================
# XÁC THỰC
# =========================================================================
def get_credentials():
    """Lấy OAuth credentials, tái dùng token.json nếu còn hạn."""
    _require_google_api()
    creds = None
    if os.path.exists(TOKEN_FILE):
        # Refresh token cho phép truy cập lâu dài, không để user khác trên máy đọc.
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError as e:
            print(f"  [!] Không thể đặt quyền 0600 cho {TOKEN_FILE}: {e}")
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Ưu tiên OAuth client từ .env, fallback về file client_secret.json.
            flow = _flow_from_env()
            if flow is None:
                if not os.path.exists(CLIENT_SECRET_FILE):
                    sys.exit(
                        "Không có OAuth client. Cách 1: đặt CLIENT_ID và CLIENT_SECRET "
                        f"trong .env. Cách 2: đặt file {CLIENT_SECRET_FILE} cùng thư mục.\n"
                        "Xem README_youtube_setup.md để tạo OAuth client (Desktop app)."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            # Chạy flow khớp đúng REDIRECT_URI (kể cả path tùy chỉnh).
            creds = _run_flow(flow)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        os.chmod(TOKEN_FILE, 0o600)
    return creds


# =========================================================================
# YOUTUBE DATA API v3 — stats + comments
# =========================================================================
def fetch_video_stats(data_api, video_ids):
    """Metadata + statistics giàu tín hiệu cho mỗi video."""
    out = {}
    # API cho phép tối đa 50 id / lần gọi.
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        resp = (
            data_api.videos()
            .list(
                part=(
                    "snippet,statistics,contentDetails,status,"
                    "topicDetails,localizations"
                ),
                id=",".join(chunk),
            )
            .execute(num_retries=READ_RETRIES)
        )
        for item in resp.get("items", []):
            stats = item.get("statistics", {})
            snip = item.get("snippet", {})
            details = item.get("contentDetails", {})
            status = item.get("status", {})
            out[item["id"]] = {
                "title": snip.get("title"),
                "description": snip.get("description"),
                "tags": snip.get("tags", []),
                "categoryId": snip.get("categoryId"),
                "publishedAt": snip.get("publishedAt"),
                "channelId": snip.get("channelId"),
                "channelTitle": snip.get("channelTitle"),
                "defaultLanguage": snip.get("defaultLanguage"),
                "defaultAudioLanguage": snip.get("defaultAudioLanguage"),
                "liveBroadcastContent": snip.get("liveBroadcastContent"),
                "thumbnails": snip.get("thumbnails", {}),
                "duration_iso": details.get("duration"),
                "definition": details.get("definition"),
                "dimension": details.get("dimension"),
                "caption_available": details.get("caption") == "true",
                "licensedContent": details.get("licensedContent"),
                "regionRestriction": details.get("regionRestriction"),
                "viewCount": int(stats.get("viewCount", 0)),
                "likeCount": int(stats.get("likeCount", 0)),
                "commentCount": int(stats.get("commentCount", 0)),
                "favoriteCount": int(stats.get("favoriteCount", 0)),
                "privacyStatus": status.get("privacyStatus"),
                "license": status.get("license"),
                "embeddable": status.get("embeddable"),
                "publicStatsViewable": status.get("publicStatsViewable"),
                "madeForKids": status.get("madeForKids"),
                "selfDeclaredMadeForKids": status.get("selfDeclaredMadeForKids"),
                "containsSyntheticMedia": status.get("containsSyntheticMedia"),
                "topicCategories": item.get("topicDetails", {}).get(
                    "topicCategories", []
                ),
                "localizations": item.get("localizations", {}),
            }
    return out


def _fetch_comment_replies(data_api, parent_id, max_replies):
    """Lấy reply đầy đủ của một top-level comment."""
    replies = []
    page_token = None
    while len(replies) < max_replies:
        remaining = max_replies - len(replies)
        resp = (
            data_api.comments()
            .list(
                part="snippet",
                parentId=parent_id,
                maxResults=min(100, remaining),
                pageToken=page_token,
                textFormat="plainText",
            )
            .execute(num_retries=READ_RETRIES)
        )
        for item in resp.get("items", []):
            snip = item.get("snippet", {})
            replies.append(
                {
                    "commentId": item.get("id"),
                    "text": snip.get("textDisplay"),
                    "likeCount": snip.get("likeCount", 0),
                    "publishedAt": snip.get("publishedAt"),
                    "updatedAt": snip.get("updatedAt"),
                    "authorDisplayName": snip.get("authorDisplayName"),
                    "authorChannelId": (
                        snip.get("authorChannelId") or {}
                    ).get("value"),
                }
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return replies[:max_replies]


def fetch_comments(
    data_api,
    video_id,
    max_comments=500,
    include_replies=True,
    max_replies_per_thread=100,
):
    """Kéo top-level comments và tùy chọn toàn bộ reply của từng thread.

    Trả về (comments, status):
      status = "ok"       -> lấy được, có thể rỗng nếu video chưa có comment
      status = "error: …" -> gọi API lỗi (vd bị tắt comment, thiếu quyền)
    """
    comments = []
    page_token = None
    while len(comments) < max_comments:
        remaining = max_comments - len(comments)
        try:
            resp = (
                data_api.commentThreads()
                .list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=min(100, remaining),
                    order="relevance",
                    textFormat="plainText",
                    pageToken=page_token,
                )
                .execute(num_retries=READ_RETRIES)
            )
        except HttpError as e:
            # Comment có thể bị tắt / thiếu quyền -> báo lỗi, không làm chết script.
            print(f"  [!] Không lấy được comment cho {video_id}: {e}")
            return comments, f"error: {e}"

        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            top_id = item["snippet"]["topLevelComment"].get("id")
            reply_count = item["snippet"].get("totalReplyCount", 0)
            replies = []
            if include_replies and reply_count and max_replies_per_thread > 0:
                try:
                    replies = _fetch_comment_replies(
                        data_api, top_id, max_replies_per_thread
                    )
                except HttpError as e:
                    print(f"    [!] Không lấy được replies cho {top_id}: {e}")
            comments.append(
                {
                    "threadId": item.get("id"),
                    "commentId": top_id,
                    "text": top.get("textDisplay"),
                    "likeCount": top.get("likeCount", 0),
                    "publishedAt": top.get("publishedAt"),
                    "updatedAt": top.get("updatedAt"),
                    "authorDisplayName": top.get("authorDisplayName"),
                    "authorChannelId": (
                        top.get("authorChannelId") or {}
                    ).get("value"),
                    "replyCount": reply_count,
                    "repliesFetched": len(replies),
                    "replies": replies,
                }
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # Sắp theo like giảm dần để câu cộng hưởng nhất nằm trên đầu.
    comments.sort(key=lambda c: c["likeCount"], reverse=True)
    return comments[:max_comments], "ok"


# =========================================================================
# YOUTUBE ANALYTICS API v2 — retention, audience, traffic source
# =========================================================================
def _channel_info(data_api):
    """Trả (channel_id, uploads_playlist_id) của kênh đang đăng nhập."""
    resp = (
        data_api.channels()
        .list(part="id,contentDetails", mine=True)
        .execute(num_retries=READ_RETRIES)
    )
    items = resp.get("items", [])
    if not items:
        sys.exit("Tài khoản đăng nhập không sở hữu kênh nào.")
    ch = items[0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    return ch["id"], uploads


def list_videos_in_range(data_api, uploads_playlist, start_date, end_date):
    """Liệt kê videoId đăng trong khoảng [start_date, end_date] (YYYY-MM-DD).

    Duyệt uploads playlist (đã sắp mới -> cũ), dừng sớm khi vượt quá start_date.
    Trả list[str] videoId, sắp theo ngày đăng tăng dần (cũ -> mới).
    """
    # So sánh theo ngày. end_date tính cả trọn ngày đó.
    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)

    picked = []  # (published_date, videoId)
    page_token = None
    while True:
        resp = (
            data_api.playlistItems()
            .list(
                part="contentDetails",
                playlistId=uploads_playlist,
                maxResults=50,
                pageToken=page_token,
            )
            .execute(num_retries=READ_RETRIES)
        )
        stop = False
        for item in resp.get("items", []):
            cd = item["contentDetails"]
            published = cd.get("videoPublishedAt")  # ISO 8601, có thể thiếu nếu video riêng tư
            if not published:
                continue
            pub_date = dt.datetime.fromisoformat(
                published.replace("Z", "+00:00")
            ).date()
            if pub_date < start:
                # Playlist sắp mới -> cũ, gặp video cũ hơn start thì dừng hẳn.
                stop = True
                break
            if pub_date <= end:
                picked.append((pub_date, cd["videoId"]))
        page_token = resp.get("nextPageToken")
        if stop or not page_token:
            break

    picked.sort(key=lambda x: x[0])  # cũ -> mới
    return [vid for _, vid in picked]


def fetch_analytics(yta, channel_id, video_id, start_date, end_date):
    """Gọi nhiều query báo cáo cho 1 video, gộp lại 1 dict."""
    ids = f"channel=={channel_id}"
    result = {}

    def q(**kwargs):
        return (
            yta.reports()
            .query(ids=ids, **kwargs)
            .execute(num_retries=READ_RETRIES)
        )

    filt = f"video=={video_id}"

    # --- (1) Chỉ số tổng: views, CTR, thời lượng xem, sub ---
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics=(
                "engagedViews,views,estimatedMinutesWatched,averageViewDuration,"
                "averageViewPercentage,subscribersGained,subscribersLost,"
                "likes,dislikes,comments,shares,"
                "videosAddedToPlaylists,videosRemovedFromPlaylists"
            ),
            filters=filt,
        )
        result["summary"] = _rows_to_dicts(r)
    except HttpError as e:
        result["summary_error"] = str(e)

    # --- (2) CTR + impressions ---
    # LƯU Ý: impressions và impressionClickThroughRate KHÔNG có trong
    # YouTube Analytics API công khai (chỉ hiển thị trong YouTube Studio).
    # Gọi sẽ trả 400 "Unknown identifier", nên không query nữa.
    # Muốn xem CTR: YouTube Studio -> video -> tab "Số liệu phân tích" ->
    # "Phạm vi tiếp cận" -> "Tỷ lệ nhấp qua số lần hiển thị".
    result["ctr"] = None
    result["ctr_note"] = (
        "Analytics Query API không trả CTR. Chạy --setup-reporting một lần, "
        "sau đó --sync-reporting để lấy impressions/CTR từ Reporting API."
    )

    # --- (3) Retention theo mốc thời gian (VÀNG) ---
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="audienceWatchRatio,relativeRetentionPerformance",
            dimensions="elapsedVideoTimeRatio",
            filters=filt,
        )
        result["retention"] = _rows_to_dicts(r)
    except HttpError as e:
        result["retention_error"] = str(e)

    # --- (4) Traffic source ---
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType",
            filters=filt,
            sort="-views",
        )
        result["traffic_source"] = _rows_to_dicts(r)
    except HttpError as e:
        result["traffic_source_error"] = str(e)

    # --- (5) Nhân khẩu học: tuổi + giới tính (viewerPercentage) ---
    # Kiểm chứng thực tế ai đang xem so với persona giả định.
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="viewerPercentage",
            dimensions="ageGroup,gender",
            filters=filt,
            sort="-viewerPercentage",
        )
        result["demographics"] = _rows_to_dicts(r)
    except HttpError as e:
        result["demographics_error"] = str(e)

    # --- (6) Từ khoá tìm kiếm dẫn tới video (YT_SEARCH) ---
    # Chính ngôn ngữ khán giả gõ để tìm ra video -> vàng cho SEO title.
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceDetail",
            filters=f"{filt};insightTrafficSourceType==YT_SEARCH",
            sort="-views",
            maxResults=25,
        )
        result["search_terms"] = _rows_to_dicts(r)
    except HttpError as e:
        result["search_terms_error"] = str(e)

    # --- (7) Video giới thiệu chéo (RELATED_VIDEO) ---
    # Video nào (của mình / đối thủ) đang đẩy traffic sang -> gợi ý chuỗi next-video.
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceDetail",
            filters=f"{filt};insightTrafficSourceType==RELATED_VIDEO",
            sort="-views",
            maxResults=25,
        )
        result["related_videos"] = _rows_to_dicts(r)
    except HttpError as e:
        result["related_videos_error"] = str(e)

    # --- (8) Chuỗi view theo ngày ---
    # Video bốc lên (YouTube đẩy Suggested) hay chết sau 48h?
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="day",
            filters=filt,
            sort="day",
        )
        result["views_by_day"] = _rows_to_dicts(r)
    except HttpError as e:
        result["views_by_day_error"] = str(e)

    # --- (9) Sub vs non-sub ---
    # Người lạ bỏ sớm còn sub xem hết? -> vấn đề nằm ở hook thu hút người mới.
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics=(
                "views,estimatedMinutesWatched,averageViewDuration,"
                "averageViewPercentage"
            ),
            dimensions="subscribedStatus",
            filters=filt,
        )
        result["by_subscribed_status"] = _rows_to_dicts(r)
    except HttpError as e:
        result["by_subscribed_status_error"] = str(e)

    # --- (10) Quốc gia ---
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics=(
                "views,estimatedMinutesWatched,averageViewDuration,"
                "averageViewPercentage"
            ),
            dimensions="country",
            filters=filt,
            sort="-views",
            maxResults=50,
        )
        result["geography"] = _rows_to_dicts(r)
    except HttpError as e:
        result["geography_error"] = str(e)

    # --- (11) Thiết bị + hệ điều hành ---
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="engagedViews,views,estimatedMinutesWatched",
            dimensions="deviceType,operatingSystem",
            filters=filt,
            sort="-views",
        )
        result["device_os"] = _rows_to_dicts(r)
    except HttpError as e:
        result["device_os_error"] = str(e)

    # --- (12) Video được xem ở đâu: watch page, embedded, channel... ---
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightPlaybackLocationType",
            filters=filt,
            sort="-views",
        )
        result["playback_location"] = _rows_to_dicts(r)
    except HttpError as e:
        result["playback_location_error"] = str(e)

    # --- (13) Website/app bên ngoài đang nhúng video ---
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightPlaybackLocationDetail",
            filters=f"{filt};insightPlaybackLocationType==EMBEDDED",
            sort="-views",
            maxResults=25,
        )
        result["embedded_playback_sources"] = _rows_to_dicts(r)
    except HttpError as e:
        result["embedded_playback_sources_error"] = str(e)

    # --- (14) URL ngoài YouTube dẫn người xem đến video ---
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceDetail",
            filters=f"{filt};insightTrafficSourceType==EXT_URL",
            sort="-views",
            maxResults=25,
        )
        result["external_referrers"] = _rows_to_dicts(r)
    except HttpError as e:
        result["external_referrers_error"] = str(e)

    # --- (15) Dịch vụ chia sẻ tạo ra lượt share ---
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics="shares",
            dimensions="sharingService",
            filters=filt,
            sort="-shares",
            maxResults=25,
        )
        result["sharing_services"] = _rows_to_dicts(r)
    except HttpError as e:
        result["sharing_services_error"] = str(e)

    # --- (16) Hiệu quả cards/teasers ---
    try:
        r = q(
            startDate=start_date,
            endDate=end_date,
            metrics=(
                "cardImpressions,cardClicks,cardClickRate,"
                "cardTeaserImpressions,cardTeaserClicks,cardTeaserClickRate"
            ),
            filters=filt,
        )
        result["cards"] = _rows_to_dicts(r)
    except HttpError as e:
        result["cards_error"] = str(e)

    return result


def _rows_to_dicts(report):
    """Chuyển kết quả Analytics (columnHeaders + rows) thành list[dict]."""
    headers = [h["name"] for h in report.get("columnHeaders", [])]
    return [dict(zip(headers, row)) for row in report.get("rows", [])]


# =========================================================================
# YOUTUBE REPORTING API — bulk CSV, đặc biệt Reach/impressions/CTR
# =========================================================================
def _paginate(request_factory, collection_key):
    """Yield items từ một list endpoint dùng nextPageToken."""
    page_token = None
    while True:
        request = request_factory(page_token)
        response = request.execute(num_retries=READ_RETRIES)
        yield from response.get(collection_key, [])
        page_token = response.get("nextPageToken")
        if not page_token:
            break


def setup_reporting_jobs(reporting_api):
    """Tạo các job phân tích giá trị cao nếu channel chưa có."""
    available = {
        item["id"]: item
        for item in _paginate(
            lambda token: reporting_api.reportTypes().list(pageToken=token),
            "reportTypes",
        )
    }
    existing = {
        item["reportTypeId"]: item
        for item in _paginate(
            lambda token: reporting_api.jobs().list(pageToken=token),
            "jobs",
        )
    }

    result = {"created": [], "existing": [], "unavailable": []}
    for report_type, description in REPORT_TYPES.items():
        if report_type not in available:
            result["unavailable"].append(report_type)
            continue
        if report_type in existing:
            result["existing"].append(
                {
                    "reportTypeId": report_type,
                    "jobId": existing[report_type]["id"],
                    "name": existing[report_type].get("name"),
                }
            )
            continue
        job = (
            reporting_api.jobs()
            .create(
                body={
                    "reportTypeId": report_type,
                    "name": f"youtube_pull — {description}",
                }
            )
            .execute()
        )
        result["created"].append(
            {
                "reportTypeId": report_type,
                "jobId": job["id"],
                "name": job.get("name"),
            }
        )
    return result


def _convert_csv_value(value):
    """Đổi số trong CSV sang int/float, giữ nguyên id/date/text."""
    if value == "":
        return None
    try:
        if value.lstrip("-").isdigit():
            return int(value)
        return float(value)
    except (AttributeError, ValueError):
        return value


def _report_overlaps_window(report, start_date, end_date):
    """Report dùng khoảng thời gian ISO; giữ file có giao với cửa sổ cần lấy."""
    report_start = (report.get("startTime") or "")[:10]
    report_end = (report.get("endTime") or "")[:10]
    if not report_start or not report_end:
        return True
    return report_start <= end_date and report_end >= start_date


def _latest_reports(reporting_api, job_id, start_date, end_date):
    """Lấy bản mới nhất cho mỗi kỳ báo cáo, bỏ các backfill cũ hơn."""
    reports = _paginate(
        lambda token: reporting_api.jobs()
        .reports()
        .list(jobId=job_id, pageToken=token),
        "reports",
    )
    latest = {}
    for report in reports:
        if not _report_overlaps_window(report, start_date, end_date):
            continue
        key = (report.get("startTime"), report.get("endTime"))
        if key not in latest or report.get("createTime", "") > latest[key].get(
            "createTime", ""
        ):
            latest[key] = report
    return sorted(latest.values(), key=lambda r: r.get("startTime", ""))


def _download_report_rows(session, download_url):
    response = session.get(download_url, timeout=60)
    response.raise_for_status()
    return [
        {key: _convert_csv_value(value) for key, value in row.items()}
        for row in csv.DictReader(io.StringIO(response.text))
    ]


def _attach_reach_summary(output, rows):
    """Gắn Reach Basic vào từng video và tính CTR có trọng số impressions."""
    by_video = {}
    for row in rows:
        video_id = row.get("video_id")
        if video_id:
            by_video.setdefault(video_id, []).append(row)

    for video_id, video in output.get("videos", {}).items():
        daily = sorted(by_video.get(video_id, []), key=lambda r: r.get("date", ""))
        impressions = sum((row.get("video_thumbnail_impressions") or 0) for row in daily)
        weighted_clicks = sum(
            (row.get("video_thumbnail_impressions") or 0)
            * (row.get("video_thumbnail_impressions_ctr") or 0)
            for row in daily
        )
        analytics = video.setdefault("analytics", {})
        analytics["reach"] = {
            "impressions": impressions,
            "impressions_ctr": weighted_clicks / impressions if impressions else None,
            "by_day": daily,
            "source": "YouTube Reporting API / channel_reach_basic_a1",
        }


def sync_reporting_data(reporting_api, credentials, output):
    """Download bulk reports và ghép các row liên quan vào output hiện tại."""
    window = output.get("analytics_window", {})
    start_date = window.get("start")
    end_date = window.get("end")
    if not (start_date and end_date):
        raise ValueError("Output thiếu analytics_window.start/end")

    video_ids = set(output.get("videos", {}))
    jobs = list(
        _paginate(
            lambda token: reporting_api.jobs().list(pageToken=token),
            "jobs",
        )
    )
    session = AuthorizedSession(credentials)
    report_data = {}
    errors = {}

    for job in jobs:
        report_type = job.get("reportTypeId")
        if report_type not in REPORT_TYPES:
            continue
        rows = []
        downloaded = 0
        for report in _latest_reports(
            reporting_api, job["id"], start_date, end_date
        ):
            try:
                report_rows = _download_report_rows(
                    session, report["downloadUrl"]
                )
                downloaded += 1
            except Exception as e:
                errors.setdefault(report_type, []).append(str(e))
                continue
            for row in report_rows:
                row_date = str(row.get("date") or "")
                row_video = row.get("video_id")
                if row_date and not (start_date <= row_date <= end_date):
                    continue
                if row_video and video_ids and row_video not in video_ids:
                    continue
                rows.append(row)
        report_data[report_type] = {
            "description": REPORT_TYPES[report_type],
            "jobId": job["id"],
            "files_downloaded": downloaded,
            "rows": rows,
        }

    output["reporting"] = {
        "synced_at": dt.datetime.now().astimezone().isoformat(),
        "report_types": report_data,
        "errors": errors,
    }
    basic = report_data.get("channel_reach_basic_a1", {}).get("rows", [])
    _attach_reach_summary(output, basic)
    return output


def _write_json_atomic(path, data):
    """Ghi JSON an toàn: chỉ thay file đích sau khi serialize thành công."""
    target = os.path.abspath(path)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".youtube_pull.", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, target)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _prompt_menu_choice(valid_choices):
    while True:
        choice = input("\nChọn chức năng: ").strip()
        if choice in valid_choices:
            return choice
        print("Lựa chọn không hợp lệ. Vui lòng nhập " + "/".join(valid_choices) + ".")


def _prompt_date(label, default):
    while True:
        value = input(f"{label} [{default}]: ").strip() or default
        try:
            dt.date.fromisoformat(value)
            return value
        except ValueError:
            print("Ngày không hợp lệ. Dùng định dạng YYYY-MM-DD.")


def _show_output_status(path):
    if not os.path.exists(path):
        print(f"\nOutput: {path} (chưa có)")
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        video_count = len(data.get("videos", {}))
        schema = data.get("schema_version", 1)
        synced_at = data.get("reporting", {}).get("synced_at")
        print(f"\nOutput: {path} — schema {schema}, {video_count} video")
        if synced_at:
            print(f"Reporting sync gần nhất: {synced_at}")
    except (OSError, json.JSONDecodeError):
        print(f"\nOutput: {path} (không đọc được trạng thái)")


def interactive_menu(args):
    """Cập nhật argparse namespace dựa trên lựa chọn tương tác."""
    today = dt.date.today()
    default_start = args.start_date or (today - dt.timedelta(days=90)).isoformat()
    default_end = args.end_date or today.isoformat()

    while True:
        configured = (
            f"{len(args.videos)} video từ .env"
            if args.videos
            else "video trong 90 ngày gần nhất"
        )
        print("\n" + "=" * 62)
        print(" YOUTUBE ANALYTICS COLLECTOR")
        print("=" * 62)
        _show_output_status(args.out)
        print(f"\n  1. Kéo data đầy đủ ({configured})  [Khuyến nghị]")
        print("  2. Nhập video ID rồi kéo data")
        print("  3. Tự tìm video theo khoảng ngày")
        print("  4. Setup Reporting API cho CTR/Reach (chạy một lần)")
        print("  5. Sync CTR/Reach và bulk reports vào output")
        print("  0. Thoát")

        choice = _prompt_menu_choice({"0", "1", "2", "3", "4", "5"})
        if choice == "0":
            return False
        if choice == "1":
            args.setup_reporting = False
            args.sync_reporting = False
            return True
        if choice == "2":
            while True:
                raw = input("Nhập video ID (cách nhau bằng dấu cách hoặc dấu phẩy): ")
                videos = raw.replace(",", " ").split()
                if videos:
                    args.videos = videos
                    args.setup_reporting = False
                    args.sync_reporting = False
                    return True
                print("Bạn cần nhập ít nhất một video ID.")
        if choice == "3":
            args.videos = None
            while True:
                args.start_date = _prompt_date("Ngày bắt đầu", default_start)
                args.end_date = _prompt_date("Ngày kết thúc", default_end)
                if args.start_date <= args.end_date:
                    break
                print("Ngày bắt đầu không được sau ngày kết thúc. Nhập lại.")
            args.setup_reporting = False
            args.sync_reporting = False
            return True
        if choice == "4":
            args.setup_reporting = True
            args.sync_reporting = False
            return True
        if choice == "5":
            args.setup_reporting = False
            args.sync_reporting = True
            return True


# =========================================================================
# MAIN
# =========================================================================
def main():
    ap = argparse.ArgumentParser(
        description="Lấy data YouTube (stats + comments + analytics) cho việc phân tích."
    )
    # Giá trị mặc định lấy từ .env (nếu có), CLI vẫn ghi đè được.
    env_videos = os.getenv("VIDEOS")  # vd: "ID1 ID2 ID3" (cách nhau bằng dấu cách)
    default_videos = env_videos.split() if env_videos else None

    ap.add_argument(
        "--videos",
        nargs="+",
        default=default_videos,
        help=(
            "Danh sách videoId. Nếu bỏ trống, tự tìm video đăng trong khoảng ngày. "
            "(hoặc đặt VIDEOS trong .env)"
        ),
    )
    ap.add_argument(
        "--out",
        default=os.getenv("OUT", "data/channels/youtube_data.json"),
        help="File JSON đầu ra. (hoặc đặt OUT trong .env)",
    )
    ap.add_argument(
        "--start-date",
        default=os.getenv("START_DATE"),
        help="Ngày bắt đầu YYYY-MM-DD cho Analytics (mặc định: 90 ngày trước).",
    )
    ap.add_argument(
        "--end-date",
        default=os.getenv("END_DATE"),
        help="Ngày kết thúc YYYY-MM-DD cho Analytics (mặc định: hôm nay).",
    )
    ap.add_argument(
        "--max-comments",
        type=int,
        default=int(os.getenv("MAX_COMMENTS", "500")),
        help="Số comment tối đa mỗi video. (hoặc đặt MAX_COMMENTS trong .env)",
    )
    ap.add_argument(
        "--max-replies-per-thread",
        type=int,
        default=int(os.getenv("MAX_REPLIES_PER_THREAD", "100")),
        help="Số reply tối đa cho mỗi comment thread. Mặc định 100.",
    )
    ap.add_argument(
        "--no-replies",
        action="store_true",
        help="Không lấy reply của comment (nhanh và ít API call hơn).",
    )
    reporting_actions = ap.add_mutually_exclusive_group()
    reporting_actions.add_argument(
        "--connect",
        action="store_true",
        help="Chỉ thực hiện OAuth và lưu/refresh token, không kéo dữ liệu.",
    )
    reporting_actions.add_argument(
        "--setup-reporting",
        action="store_true",
        help="Tạo các Reporting API jobs cho Reach/CTR, cards, end screen...",
    )
    reporting_actions.add_argument(
        "--sync-reporting",
        action="store_true",
        help="Tải bulk reports đã sẵn sàng và ghép vào file --out.",
    )
    args = ap.parse_args()

    if args.connect:
        print("Đang xác thực với Google...")
        get_credentials()
        print("Kết nối Google/YouTube thành công.")
        return

    # Không truyền tham số là cách dùng mặc định: luôn mở menu.
    if len(sys.argv) == 1:
        if not interactive_menu(args):
            print("Đã thoát.")
            return

    today = dt.date.today()
    start_date = args.start_date or (today - dt.timedelta(days=90)).isoformat()
    end_date = args.end_date or today.isoformat()
    try:
        start = dt.date.fromisoformat(start_date)
        end = dt.date.fromisoformat(end_date)
    except ValueError:
        ap.error("--start-date/--end-date phải có định dạng YYYY-MM-DD")
    if start > end:
        ap.error("--start-date không được sau --end-date")
    if args.max_comments < 0:
        ap.error("--max-comments phải >= 0")
    if args.max_replies_per_thread < 0:
        ap.error("--max-replies-per-thread phải >= 0")

    print("Đang xác thực với Google...")
    creds = get_credentials()

    if args.setup_reporting:
        reporting_api = build("youtubereporting", "v1", credentials=creds)
        print("Kiểm tra và tạo Reporting API jobs...")
        result = setup_reporting_jobs(reporting_api)
        print(f"  Đã tạo mới: {len(result['created'])}")
        print(f"  Đã tồn tại: {len(result['existing'])}")
        if result["unavailable"]:
            print("  Channel chưa hỗ trợ: " + ", ".join(result["unavailable"]))
        print(
            "Xong. Report mới thường cần khoảng 48 giờ để xuất hiện; "
            "sau đó chạy lại với --sync-reporting."
        )
        return

    if args.sync_reporting:
        if not os.path.exists(args.out):
            sys.exit(
                f"Không tìm thấy {args.out}. Hãy chạy kéo dữ liệu thường trước "
                "rồi mới --sync-reporting."
            )
        with open(args.out, encoding="utf-8") as f:
            output = json.load(f)
        reporting_api = build("youtubereporting", "v1", credentials=creds)
        print("Tải các bulk report đã sẵn sàng...")
        sync_reporting_data(reporting_api, creds, output)
        _write_json_atomic(args.out, output)
        report_types = output.get("reporting", {}).get("report_types", {})
        total_rows = sum(len(item.get("rows", [])) for item in report_types.values())
        print(f"Xong. Đã ghép {total_rows} dòng reporting vào {args.out}")
        return

    data_api = build("youtube", "v3", credentials=creds)
    yta = build("youtubeAnalytics", "v2", credentials=creds)

    print("Lấy channel id...")
    channel_id, uploads_playlist = _channel_info(data_api)

    # Xác định danh sách video: ưu tiên chỉ định thủ công, nếu không thì
    # tự tìm mọi video đăng trong khoảng [start_date, end_date].
    videos = args.videos
    if videos:
        print(f"Dùng {len(videos)} video chỉ định sẵn.")
    else:
        print(f"Tìm video đăng trong khoảng {start_date} .. {end_date}...")
        videos = list_videos_in_range(data_api, uploads_playlist, start_date, end_date)
        if not videos:
            sys.exit(
                f"Không có video nào đăng trong khoảng {start_date} .. {end_date}.\n"
                "Kiểm tra lại START_DATE / END_DATE trong .env, hoặc chỉ định --videos."
            )
        print(f"Tìm thấy {len(videos)} video: {', '.join(videos)}")

    print("Lấy stats cơ bản (Data API)...")
    stats = fetch_video_stats(data_api, videos)

    output = {
        "schema_version": 2,
        "generated_at": dt.datetime.now().astimezone().isoformat(),
        "channel_id": channel_id,
        "analytics_window": {"start": start_date, "end": end_date},
        "videos": {},
    }

    for vid in videos:
        print(f"\n=== Video {vid} ===")
        v = {"videoId": vid}
        v.update(stats.get(vid, {"warning": "không thấy trong Data API (id sai?)"}))

        print("  - Lấy comments...")
        comments, status = fetch_comments(
            data_api,
            vid,
            args.max_comments,
            include_replies=not args.no_replies,
            max_replies_per_thread=args.max_replies_per_thread,
        )
        v["comments"] = comments
        v["comments_fetched"] = len(comments)
        v["comments_status"] = status  # "ok" | "error: ..."
        if status == "ok" and not comments:
            print("    (video này chưa có comment nào)")

        print("  - Lấy analytics (retention, audience, traffic)...")
        v["analytics"] = fetch_analytics(yta, channel_id, vid, start_date, end_date)

        output["videos"][vid] = v

    _write_json_atomic(args.out, output)

    print(f"\nXong. Đã ghi {args.out}")
    print("Gửi file này cho Claude để phân tích. (KHÔNG gửi client_secret.json / token.json)")


if __name__ == "__main__":
    main()
