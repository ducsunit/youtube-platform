# YouTube Analytics Collector

`youtube_pull.py` gom dữ liệu phục vụ phân tích nội dung từ ba API chính thức:

- **YouTube Data API v3:** metadata, stats, top-level comments và replies.
- **YouTube Analytics API v2:** retention, watch time, traffic source, search terms,
  geography, device/OS, playback location, subscriber status và cards.
- **YouTube Reporting API v1:** bulk reports theo ngày, gồm thumbnail impressions,
  CTR, cards, end screens, subtitles và retention.

Script chỉ yêu cầu hai OAuth scope đọc:

- `youtube.readonly`
- `yt-analytics.readonly`

Không gửi `.env`, `client_secret.json` hoặc `token.json` cho người khác.

## 1. Cài đặt

Khuyến nghị dùng virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 2. Tạo Google Cloud project

1. Mở [Google Cloud Console](https://console.cloud.google.com/).
2. Tạo hoặc chọn một project.
3. Vào **APIs & Services → Library** và bật:
   - YouTube Data API v3
   - YouTube Analytics API
   - YouTube Reporting API

## 3. Cấu hình OAuth

1. Vào **APIs & Services → OAuth consent screen**.
2. Tạo consent screen và thêm tài khoản sở hữu channel vào **Test users** nếu
   ứng dụng còn ở chế độ Testing.
3. Vào **Credentials → Create Credentials → OAuth client ID**.
4. Chọn **Desktop app**, tải JSON, đổi tên thành `client_secret.json` và đặt cạnh
   script.

Lần chạy đầu, trình duyệt sẽ mở để xin quyền đọc. Token được lưu vào
`token.json` với quyền file `0600`.

Nếu trước đây đã dùng phiên bản script xin scope `youtube.force-ssl`, hãy thu hồi
quyền ứng dụng trong Google Account hoặc xóa `token.json`, sau đó đăng nhập lại.

## 4. Mở menu

Cách dùng đơn giản nhất:

```bash
python -m youtube_pipeline.analysis.youtube_pull
```

Khi chạy trực tiếp trong terminal, menu sẽ hiển thị:

```text
1. Kéo data đầy đủ cho video đã cấu hình
2. Nhập video ID rồi kéo data
3. Tự tìm video theo khoảng ngày
4. Setup Reporting API cho CTR/Reach
5. Sync CTR/Reach và bulk reports
0. Thoát
```

Không cần thêm `--menu`, `--videos` hoặc tham số nào cho cách dùng thông thường.
Các tham số CLI bên dưới chỉ dành cho automation hoặc nhu cầu nâng cao.

## 5. Kéo dữ liệu bằng CLI

Chỉ định video:

```bash
python -m youtube_pipeline.analysis.youtube_pull --videos VIDEO_ID_1 VIDEO_ID_2 --out youtube_data.json
```

Hoặc tự tìm toàn bộ video đăng trong khoảng ngày:

```bash
python -m youtube_pipeline.analysis.youtube_pull \
  --start-date 2026-07-01 \
  --end-date 2026-07-28 \
  --out youtube_data.json
```

Mặc định script lấy tối đa 500 top-level comments và tối đa 100 replies cho mỗi
thread:

```bash
python -m youtube_pipeline.analysis.youtube_pull \
  --videos VIDEO_ID \
  --max-comments 1000 \
  --max-replies-per-thread 200
```

Nếu cần chạy nhanh và tiết kiệm Data API calls:

```bash
python -m youtube_pipeline.analysis.youtube_pull --videos VIDEO_ID --no-replies
```

Có thể sao chép `.env.example` thành `.env` để lưu cấu hình mặc định.

## 6. Bật Reporting API để lấy impressions và CTR

Analytics Query API không trả thumbnail impressions/CTR. Reporting API cung cấp
hai trường này qua Reach reports nhưng hoạt động bất đồng bộ.

Tạo các reporting job một lần:

```bash
python -m youtube_pipeline.analysis.youtube_pull --setup-reporting
```

YouTube thường cần khoảng 48 giờ để tạo các report đầu tiên. Sau đó kéo dữ liệu
tức thời như Bước 5 rồi ghép bulk reports vào cùng file:

```bash
python -m youtube_pipeline.analysis.youtube_pull --sync-reporting --out youtube_data.json
```

Lặp `--sync-reporting` định kỳ để nhận report mới. Script:

- Chỉ tải report giao với `analytics_window`.
- Giữ bản backfill mới nhất cho mỗi ngày.
- Lọc đúng các video có trong file output.
- Tính CTR tổng theo trọng số impressions.

CTR sau khi sync nằm tại:

```text
videos.<VIDEO_ID>.analytics.reach.impressions
videos.<VIDEO_ID>.analytics.reach.impressions_ctr
videos.<VIDEO_ID>.analytics.reach.by_day
```

Dữ liệu bulk thô nằm tại:

```text
reporting.report_types
```

## Dữ liệu phân tích chính

Mỗi video có:

- Metadata: title, description, tags, category, thumbnail, caption, ngôn ngữ,
  trạng thái, topic và các thuộc tính nội dung.
- Public stats: views, likes và comment count.
- Comments: nội dung, likes, thời gian, tác giả công khai và replies.
- Summary: watch time, average view duration/percentage, subscribers, shares và
  playlist actions.
- Retention curve theo `elapsedVideoTimeRatio`.
- Traffic source, YouTube search terms và related videos.
- Views theo ngày và subscribed/non-subscribed.
- Geography, device/OS và playback location.
- Embedded sources, external referrers và sharing services.
- Cards và, sau khi sync Reporting API, Reach/CTR, end screen, subtitles và bulk
  retention.

Một số báo cáo demographics, search term hoặc retention có thể rỗng do channel
chưa đủ dữ liệu hoặc ngưỡng bảo mật của YouTube.

## Xử lý lỗi thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| `access_denied` | Thêm email chủ channel vào OAuth Test users. |
| `insufficientPermissions` | Xóa `token.json`, chạy lại và cấp quyền mới. |
| Reporting API chưa có report | Đợi khoảng 48 giờ sau `--setup-reporting`. |
| Report type unavailable | Tài khoản/channel chưa hỗ trợ loại report đó; script tự bỏ qua. |
| Retention/demographics rỗng | Chờ thêm dữ liệu hoặc YouTube đang áp dụng privacy threshold. |
| Comment rỗng | Video chưa có comment hoặc comment đã bị tắt. |
| `quotaExceeded` | Chờ quota reset hoặc giảm số video/comment/reply. |

## Bảo mật dữ liệu

Output không chứa OAuth token nhưng có thể chứa tên hiển thị và nội dung comment
công khai. Hãy xem đây là dữ liệu phân tích nội bộ, không công khai nguyên file nếu
không cần thiết.
