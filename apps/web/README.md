# YouTube Resource Pack — Web UI

Giao diện web quản lý pipeline tạo resource pack video YouTube (project backend:
[`youtube-v3`](../youtube-v3)). Song ngữ **VI/EN** (toggle ở header, mặc định VI).

## Tính năng

- **Danh sách run** — xem 20 stage, trạng thái, lỗi/cảnh báo, tải manifest.
- **Tạo run mới** — chế độ *Demo* (20 stage, không cần API key) hoặc *Production*
  (chọn file input JSON trong thư mục backend). Tự điều hướng sang trang chi tiết.
- **Trang chi tiết** — tiến độ stage realtime (poll `/status` 1.5s), log live tự cuộn,
  cây artifact collapsible (script/review/thumbnail/audio/video…), xem JSON/text inline,
  tải file, resume run, cancel, banner cảnh báo khi run "mồ côi" (server chết giữa chừng).
- **Kéo data YouTube** (nav "Kéo data", `/data`) — kết nối kênh YouTube (OAuth,
  chờ xác nhận trong browser + log job), kéo data theo video ID / khoảng ngày /
  tất cả video, tạo job Reporting API. File kết quả ghi ở gốc backend nên xuất
  hiện ngay trong dropdown "Tạo run mới" (production); nút "Tạo run mới với file
  này" dẫn sang trang chủ với dialog đã mở sẵn (`?input=<file>`).

## Chạy

```bash
npm install
npm run dev        # http://localhost:5173 — proxy /api → http://127.0.0.1:8787
```

Bắt buộc API server bên backend đang chạy ở `127.0.0.1:8787`:

```bash
cd ../youtube-v3
.venv/bin/python -m youtube_pipeline api-server
```

## Build production

```bash
npm run build      # tsc -b && vite build → dist/
```

Bản build có thể được phục vụ luôn bởi API server (1 process duy nhất):

```bash
YT_SERVE_FRONTEND=dist .venv/bin/python -m youtube_pipeline api-server
```

## Cấu trúc

```
src/
  api.ts            # client typed + ApiError cho mọi endpoint /api
  types.ts          # kiểu trả về từ API (RunDetail, RunStatus, LogPage, …)
  i18n.tsx          # từ điển vi/en + LanguageProvider, fallback en → key
  hooks/usePolling.ts  # poll hook (setTimeout chain, StrictMode-safe)
  components/       # Header (nav + status dot), StatusBadge, NewRunDialog, RunsTable,
                    # StageList, LogViewer (dùng chung log run + log data job),
                    # ArtifactBrowser, ArtifactViewer, ResumeButton
  pages/            # RunsPage (danh sách + tạo run), RunDetailPage (chi tiết),
                    # DataPage (kéo data YouTube)
```
