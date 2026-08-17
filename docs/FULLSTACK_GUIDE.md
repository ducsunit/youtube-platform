# 🚀 Full Stack Scripts - Backend + Frontend

Đã tạo scripts để chạy backend API + frontend React:

---

## 🎯 Quick Start (Recommended)

### Start Everything (Backend + Frontend)
```bash
./start-all.sh
```

**Mở browser:** http://localhost:5173

**Làm gì:**
- ✅ Backend API: http://127.0.0.1:8787
- ✅ Frontend UI: http://localhost:5173
- ✅ Auto proxy `/api` → backend
- ⚠️ Press Ctrl+C để stop cả 2

---

## 🔧 Start Riêng Biệt (Nếu cần debug)

### 1. Backend Only
```bash
./start-backend.sh
```
→ API server chạy ở port 8787

### 2. Frontend Only
```bash
./start-frontend.sh
```
→ Vite dev server ở port 5173

**Lưu ý:** Frontend cần backend chạy trước!

---

## 📋 Features trong UI

### Trang chủ (/)
- Danh sách runs (20 stages mỗi run)
- Tạo run mới (Demo mode hoặc Production)
- Trạng thái realtime với polling

### Chi tiết run (/runs/{id})
- Live logs tự cuộn
- 20 stages progress
- Download artifacts (script, audio, video, thumbnail...)
- Resume run nếu bị gián đoạn
- Cancel run

### Pull YouTube Data (/data)
- OAuth connect YouTube channel
- Pull data theo video ID / date range / all videos
- Export file JSON để dùng cho pipeline

---

## 🔌 API Endpoints

Backend API server cung cấp:

```
GET  /api/runs                    - List all runs
POST /api/runs                    - Create new run
  Body: {
    "mode": "production" | "demo",
    "input_file": "data/channels/youtube_data.json",  // production only
    "run_id": "optional-custom-id"
  }

GET  /api/runs/{id}/status        - Get run status + stage progress
GET  /api/runs/{id}/logs          - Get run logs (paginated)
POST /api/runs/{id}/resume        - Resume interrupted run
POST /api/runs/{id}/cancel        - Cancel running job

GET  /api/runs/{id}/artifact?path=script/script.txt  - Download artifact
GET  /api/health                  - Health check
```

---

## 📁 Directory Structure

```
youtube-v3/                       # Backend (Python)
├── start-all.sh                  # ⭐ Start everything
├── start-backend.sh              # Backend only
├── start-frontend.sh             # Frontend only
├── youtube_pipeline/             # Pipeline code
│   ├── api_server.py            # API endpoints
│   └── resource_pipeline.py     # 19-stage pipeline
└── apps/web/          # Frontend (React + Vite)
    ├── src/
    │   ├── api.ts               # Typed API client
    │   ├── types.ts             # TypeScript types
    │   ├── i18n.tsx             # VI/EN translation
    │   ├── components/          # UI components
    │   └── pages/               # Route pages
    └── vite.config.ts           # Proxy config
```

---

## 🛠️ Development Workflow

### First Time Setup:
```bash
# Backend
python3 -m venv .venv
.venv/bin/pip install -e .

# Frontend
cd apps/web
npm install
cd ..
```

### Daily Usage:
```bash
./start-all.sh
# Open http://localhost:5173
```

### Pipeline CLI (Alternative):
```bash
./run.sh video-001              # Direct CLI run (no UI)
```

---

## 🐛 Troubleshooting

**Backend won't start:**
```bash
# Check venv
ls -la .venv/bin/python

# Reinstall
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install -e .
```

**Frontend won't start:**
```bash
cd apps/web
rm -rf node_modules package-lock.json
npm install
```

**Port already in use:**
```bash
# Kill process on port 8787
lsof -ti:8787 | xargs kill -9

# Kill process on port 5173
lsof -ti:5173 | xargs kill -9
```

**API connection failed:**
- Make sure backend started successfully (green ✅)
- Check backend terminal for errors
- Try: http://127.0.0.1:8787/api/health

---

## 🎨 UI Features

- **Bilingual:** VI/EN toggle in header (default VI)
- **Live Updates:** Auto-refresh every 1.5s
- **Collapsible Artifacts:** Browse all outputs (script, audio, images, video...)
- **Inline Viewers:** JSON/text preview without download
- **Warning Banners:** Orphaned runs, resume options
- **Status Badges:** pending/running/completed/failed with colors

---

## ✅ Ready to Use

```bash
./start-all.sh
```

Mở browser → http://localhost:5173 → Bấm "Tạo run mới" → Chọn Demo/Production → Xem live logs! 🎉
