# CONTENT LIBRARY — こころ包み

Dữ liệu nội dung (topic, cơ chế, chất liệu văn hóa) — tách riêng khỏi logic skill.
Skills giữ *cách làm*; thư mục này giữ *làm cái gì*.

Nguồn: `kokorotsutsumi-checklist.md` mục H (NỘI DUNG). Đây là dữ liệu, không phải
config — mọi con số/gate vẫn reference qua `CONSTANTS.<key>` trong `skills/CHANNEL_CONSTANTS.md`.

## Files

| File | Nội dung | Ai tiêu thụ |
|---|---|---|
| `mechanisms.md` | Kho cơ chế tâm lý học, mỗi cơ chế kèm tác giả + năm | `seri` (chọn cơ chế), `script_planning`/`script_production` (đưa vào script + khối 研究引用) |
| `cultural-frames-jp.md` | Chất liệu văn hóa Nhật dùng làm khung giải thích | `script_master`/`script_planning` — lớp framing gắn theo spine psychology-first (reframe / mechanism block / insight landing / CTA) |
| `video-queue.md` | Hàng đợi 10 video tiếp theo + quy tắc re-cut sau 30 ngày | `seri` — lấy topic theo queue, cập nhật status sau khi đăng |

## Quy tắc bảo trì

- Mọi entry trong `mechanisms.md` phải có **tác giả + năm** — đây chính là nguyên
  liệu cho gate `CONSTANTS.research_min_count` và khối 研究引用 trong description.
- Sau khi đăng video: cập nhật `status` entry tương ứng trong `video-queue.md` và
  ghi cơ chế đã dùng (để enforce `CONSTANTS.mechanism_diversity_window`).
- Kho được phép lớn lên: khi một video cần cơ chế chưa có, thêm entry mới vào
  `mechanisms.md` (kèm nguồn) trước khi viết script — không dẫn nguồn miệng.
