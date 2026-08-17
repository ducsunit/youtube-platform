# 🚀 Quick Start Scripts

Đã tạo 3 scripts đơn giản để chạy pipeline:

## 1. Run Production (Chính)
```bash
./run.sh
```
Hoặc với custom run ID:
```bash
./run.sh my-video-001
```

**Làm gì:**
- Tự động tạo run ID: `psychtoons-YYYYMMDD-HHMMSS`
- Chạy full pipeline với Gemini + DeepSeek
- Output: `runs/<run-id>/`
- Hiện kết quả và commands để check

---

## 2. Run Demo (Test)
```bash
./run-demo.sh
```

**Làm gì:**
- Test pipeline KHÔNG gọi API
- Dùng mock data
- Nhanh, miễn phí

---

## 3. Resume từ Checkpoint
```bash
./run-resume.sh runs/psychtoons-001/run_state.json
```

**Làm gì:**
- Tiếp tục từ run bị gián đoạn
- Không mất tiến độ
- Không tính phí lại các stage đã xong

---

## Script Cũ (Advanced)
```bash
./run-resource-pack.sh --help
```

**Có thêm options:**
- `--demo` - Demo mode
- `--run-id ID` - Custom ID
- `--output-dir PATH` - Custom output
- `--resume PATH` - Resume

---

## Các Lệnh Hay Dùng

### Check kết quả:
```bash
# Structure score
cat runs/psychtoons-001/script/structure-check.json | jq '.structure_score, .status, .issues'

# Script cuối
cat runs/psychtoons-001/script/script.txt

# Planning sections
cat runs/psychtoons-001/script/planning.json | jq '.sections[] | {id, purpose}'

# Title
cat runs/psychtoons-001/script/contract.json | jq '.title, .target_duration_min'
```

### Xem runs gần nhất:
```bash
ls -lt runs/ | head -5
```

### Xem logs nếu lỗi:
```bash
tail -100 runtime/logs/model_pipeline_calls.log
```

---

## Workflow Chuẩn

**Lần đầu:**
```bash
./run.sh test-001
cat runs/test-001/script/structure-check.json | jq '.structure_score'
```

**Nếu ổn → Production:**
```bash
./run.sh video-001
```

**Nếu bị gián đoạn:**
```bash
./run-resume.sh runs/video-001/run_state.json
```

---

## ✅ Ready to Use

Bây giờ chỉ cần gõ `./run.sh` là pipeline tự chạy với PsychToons structure 100% integrated!
