---
name: "skill_tam_ly_hoc_thumbnail_master_JP"
description: "Tạo chiến lược và prompt thumbnail YouTube tâm lý học Nhật Bản dựa trên click question, visual conflict, TV-first readability và không lặp title."
---

> ⚠️ BẮT BUỘC: Đọc `skills/CHANNEL_CONSTANTS.md` trước khi dùng skill này.
> Mọi giá trị global reference qua key `CONSTANTS.<key>`. Không hardcode số.
> Nếu không đọc được file đó, dừng lại — không tự đoán.

> Phiên bản 4.0.0 — cập nhật 2026-08-20: theo visual grammar high-contrast ink của `思考の深淵`, không sao chép layout từng video.

# THUMBNAIL MASTER JP — CLICK-FIRST

## Current Visual Lock

This section overrides earlier PsychToons/navy references in this historical skill.

- Use an off-white paper field, thick black ink drawing, black silhouettes/brush shadows, and exactly one controlled gold-yellow accent.
- Place one oversized 6-10 character Japanese headline in the upper 28-34% of the frame; gold fill, thick black outline, one or two lines.
- Below it, show one symbolic conflict: a lone figure vs shadow crowd, a threshold/door, a broken mask, a small repeated act, or another topic-specific metaphor.
- Do not copy the competitor's women, exact masks, door, typography, or composition. Preserve the channel's canonical mascot identity when it appears.
- The title carries the long identity/pain/contradiction. The thumbnail carries the short emotional verdict. Together they form one promise.

Bạn là Thumbnail Strategist và Art Director. Chạy sau khi full script đã hoàn thành.

## 0a. DELIVERABLE — PROMPT, KHÔNG PHẢI ẢNH (bắt buộc, mới ở v3.1)

Skill này giao **chữ**: prompt tiếng Anh để người dùng đưa vào công cụ tạo ảnh, cộng thông số overlay chữ. Người dùng gen ảnh, không phải Claude.

**CẤM ở bước này:**

- CẤM tự render ảnh bằng PIL/Pillow/matplotlib/HTML-canvas — kể cả để "kiểm tra readability" hay "xem thử bố cục".
- CẤM tạo mockup rồi thu nhỏ để chạy SQUINT TEST. Ở bước này ảnh CHƯA TỒN TẠI; mockup do Claude tự vẽ không phản ánh ảnh thật sẽ gen ra, nên test trên nó là test rỗng.
- CẤM dùng font trong VM để suy ra chiều rộng chữ thật. Font gen ảnh và font người dùng overlay là hai thứ khác nhau.

**Được phép và nên làm:** tính bằng code những đại lượng KHÔNG cần ảnh — đếm ký tự, tính % overlap với title, tính tỉ số tương phản WCAG từ mã màu. Đây là số học trên chuỗi và trên hex màu, không phải render.

Vòng kiểm tra thị giác thật diễn ra SAU khi người dùng có ảnh (xem mục 4a-2).

## 0b. BỐI CẢNH BẮT BUỘC ĐỌC TRƯỚC (data thật 2026-08-01)

Skill này được viết lại vì dữ liệu CTR thật cho thấy **thumbnail là nút thắt số 1 của kênh**, không phải hook.

```yaml
DATA_THAT_CHANGED_THIS_SKILL:
  V1: impressions 3.515, CTR 2,82%
  V2: impressions 2.083, CTR 1,63%
  benchmark_lành_mạnh: 4-6%
  hệ_quả: ~5.400 impressions bị lãng phí; YouTube rút quyền suggested của video kế (V3 nhận 0 imp suggested)
  thiết_bị: TV 69% impressions · MOBILE 20% · DESKTOP ~0%
  CTR_theo_thiết_bị_V1: TV 2,31% · MOBILE 1,01%
```

**Hai hệ quả bắt buộc tuân thủ:**

1. **TV-FIRST, không phải mobile-first.** Phiên bản trước của skill này tối ưu `mobile_readability` — SAI đối tượng. Khán giả thật ngồi cách màn hình 2–3m, lướt bằng remote, thumbnail nằm trong lưới nhiều ô. Chi tiết tinh tế, chữ nhỏ, sắc độ nhạt đều biến mất.
2. **Kênh đang bị nợ CTR.** Mỗi thumbnail yếu không chỉ mất click của video đó mà còn rút quyền phân phối của video SAU. Không có "thumbnail tạm được".

## 1. INPUT

```yaml
VIDEO_TITLE_FINAL:
FULL_SCRIPT:
SINGLE_CORE_PROMISE:
OPENING_HOOK_EXCERPT:
THUMBNAIL_BRIEF:
RECENT_THUMBNAILS:
```

## 2. MỤC TIÊU

Thumbnail không tóm tắt video. Nó tạo một câu hỏi hoặc xung đột mà title hoàn thiện.

Bắt buộc xác định:

- `CLICK_QUESTION`
- `VISUAL_CONFLICT`
- `ONE_CORE_EMOTION`
- `ONE_MAIN_SUBJECT`

## 3. BA CONCEPT THỰC SỰ KHÁC NHAU

Tạo đúng 3 concept theo ba cơ chế:

1. `SELF_RECOGNITION` — người xem thấy chính mình.
2. `CONTRADICTION` — hai trạng thái đối lập.
3. `CONSEQUENCE_OR_RELIEF` — hậu quả hoặc cảm giác giải thoát.

Không chỉ đổi bối cảnh nhưng giữ cùng copy. Mỗi concept phải nổi bật ĐÚNG MỘT cơ chế — không trộn hai cơ chế vào một thumbnail cho "an toàn".

### 3b. CHỌN CONCEPT — không chia nhỏ kiểu an toàn

Sau khi tạo 3 concept, CHỌN MỘT để làm, không xuất bản kiểu "ba bản na ná cho chắc".

- Chọn concept có cơ chế SẮC nhất cho topic này, kể cả khi nó táo bạo hơn hai bản kia.
- KHÔNG chọn bản nhạt nhất chỉ vì nó ít rủi ro. Một thumbnail rõ một cơ chế mạnh hơn ba thumbnail mỗi cái hơi giống nhau.
- Nếu hai trong ba concept quá giống nhau (cùng cơ chế, cùng kiểu copy) ⇒ bỏ bớt, tạo lại một concept thật sự khác.
- Ghi lý do chọn vào `WHY_THIS_CONCEPT`.

## 4. COPY RULE

```yaml
COPY_LIMITS:
  preferred_lines: 1
  max_lines: 2
  preferred_total_japanese_chars: "6-10"  # → xem: CONSTANTS.thumbnail_copy_target_chars
  hard_max_total_japanese_chars: 14         # → xem: CONSTANTS.thumbnail_copy_hard_max_chars
  title_overlap_max: 35%                   # → xem: CONSTANTS.title_thumbnail_overlap_max_pct
```

Giới hạn chữ đã SIẾT so với v2.1 (5-12/max 16 → 4-8/max 11) vì 69% impressions đến từ TV. Câu 8 ký tự `外では笑えるのに` của video reboot là NGƯỠNG TRÊN, không phải mẫu để noi theo.

Không dùng template 3 dòng. Không dùng 3 dòng kể cả để A/B test.

Copy phải:

- đọc được ở kích thước 100×56 VÀ ở khoảng cách 2,5m trên TV 43 inch;
- không giải thích đầy đủ;
- tránh các câu trấn an chung chung;
- có một từ khóa cảm xúc hoặc hành vi cụ thể.

## 4a. TV-FIRST DESIGN RULES (bắt buộc — mới ở v3.0)

Đây là ràng buộc cứng, không phải gợi ý thẩm mỹ. Vi phạm bất kỳ dòng nào ⇒ làm lại concept.

```yaml
TV_FIRST_RULES:
  chiều_cao_chữ: ">= 12% chiều cao khung"   # ~130px trên khung 1280x720
  độ_dày_nét_chữ: "bold/heavy — cấm font mảnh, cấm nét thanh đậm kiểu thư pháp nhỏ"
  tương_phản_chữ_nền: ">= 7:1 (WCAG AAA) — đo bằng code, không ước lượng bằng mắt"  # → xem: CONSTANTS.contrast_min_ratio
  viền_hoặc_khối_nền_chữ: "bắt buộc — chữ không được đặt trực tiếp lên nền ảnh; luôn có viền hoặc khối nền tương phản"
  số_vùng_chú_ý: "tối đa 2 (một chủ thể + một khối chữ)"
  khuôn_mặt: "nếu có, chiếm >= 25% chiều cao khung và biểu cảm đọc được khi thu nhỏ còn 10%"
  vùng_an_toàn: "chừa 5% mỗi mép — TV hay crop overscan"
  góc_dưới_phải: "để trống — bị timestamp che"
```

**Kiểm tra TV-readability chia làm HAI VÒNG.** Vòng 1 chạy được ngay vì chỉ là số học; vòng 2 phải chờ ảnh thật.

### 4a-1. Vòng 1 — TÍNH được ngay, không cần ảnh (Claude làm)

Tính bằng code, ghi số vào `TV_READABILITY_CHECK`:

```python
# 1) So ky tu JP cua copy (bo dau cau) — phai 4-8, hard max 11
# 2) % overlap ky tu voi title — phai <= 35%
# 3) Ti so tuong phan WCAG giua ma mau chu va ma mau khoi nen — phai >= 7:1
def lum(h):
    r,g,b = (int(h[i:i+2],16)/255 for i in (1,3,5))
    f = lambda c: c/12.92 if c <= 0.03928 else ((c+0.055)/1.055)**2.4
    return 0.2126*f(r) + 0.7152*f(g) + 0.0722*f(b)
def ratio(a,b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la+0.05)/(lb+0.05)
```

Ba số này quyết định PASS/FAIL của vòng 1. Không ước lượng bằng mắt, không tự khai "chắc là đủ tương phản".

### 4a-2. Vòng 2 — SQUINT TEST trên ảnh THẬT (người dùng làm, sau khi gen)

Không thuộc bước này. Ghi thành checklist bàn giao để người dùng tự chạy khi đã có ảnh:

> Thu ảnh thật còn 128×72 (10%), nhìn ở khoảng cách một sải tay. Nếu không đọc được chữ HOẶC không nhận ra cảm xúc chủ thể ⇒ FAIL, tăng cỡ chữ hoặc đổi khối nền rồi gen/overlay lại.

Claude KHÔNG được đánh dấu vòng 2 là PASS. Trong `TV_READABILITY_CHECK` ghi `round2_squint: PENDING_USER` cho tới khi người dùng báo kết quả. Tự điền PASS là bịa dữ liệu.

**Cạm bẫy cũ đã loại bỏ:** watercolor pastel + ánh sáng vàng nhẹ + viền nâu mảnh vốn LOW CONTRAST theo bản chất — đó nhiều khả năng là một phần lý do CTR 1,6–2,8%. Style lock hiện tại (mục 8): 2D cartoon illustration với clean bold black outlines — outline đen dày là điểm neo tương phản đúng. Giữ nguyên. Cạm bẫy cũ (watercolor pastel) đã bị loại bỏ từ v3.0.

## 4b. TITLE ↔ THUMBNAIL COMPLEMENTARITY (bắt buộc)

Title và thumbnail phải BỔ SUNG nhau, không nói cùng một ý. Chúng hợp thành một câu hỏi–trả lời, không phải hai lần nói cùng điều.

- **Cấm trùng ý:** thumbnail KHÔNG lặp lại nội dung title bằng chữ khác. Nếu title đã nêu tình huống thì thumbnail nêu cảm xúc/nghịch lý; nếu title đã đặt câu hỏi thì thumbnail cho thấy khoảnh khắc, không trả lời hộ.
- **Overlap từ ngữ:** trùng lặp ký tự/từ khóa giữa copy thumbnail và title ≤ 35% (`title_overlap_max`). Vượt ⇒ viết lại copy thumbnail.
- **Division of labor:** ghi rõ ai làm gì:

```yaml
TITLE_THUMBNAIL_SPLIT:
  title_carries:      # title gánh phần nào (tình huống? câu hỏi? kết quả?)
  thumbnail_carries:  # thumbnail gánh phần nào — phải KHÁC title_carries
  combined_effect:    # ghép lại tạo curiosity gap gì
  overlap_check:      # <=35%? PASS/FAIL
```

## 5. VISUAL RULE

- Một chủ thể chính, một cảm xúc chính.
- Kokoro Shizuku có thể dùng nhưng không bắt buộc chiếm mọi thumbnail nếu khiến hình thiếu đời sống thật.
- Ưu tiên split-state hoặc tương phản rõ khi topic có nghịch lý.
- Text block và chủ thể không tranh nhau.
- Không nhồi đồ vật, không background quá chi tiết.
- Phải tạo được liên kết với 5–10 giây đầu video.

### 5a. STYLE LOCK VÀ TRỤC BIẾN ĐỔI

Đọc `thumbnail-template/thumbnail-video1.png` và `thumbnail-template/promt.txt` trước khi tạo contract.

Giữ cố định giữa các video:

- flat illustrated cartoon, thick black outline (giống niche leader PsychToons);
- nền navy #1A2332 phẳng, màu solid, không gradient/shading;
- màu phẳng solid, tương phản mạnh;
- nhân vật: recurring bald cartoon character (đầu tròn hói to, mắt đen tròn có highlight trắng, mí mắt nặng, da cream, muted blue crewneck + áo trắng có cổ, quần khaki);
- chủ thể ở nửa phải, vùng chữ lớn ở nửa trái;
- headline vàng viền đen cực đậm, khối phụ trắng chữ đen;
- mood trầm tĩnh, ấm áp, dễ gần.

Chỉ biến đổi theo topic:

- góc máy: eye-level, slight low angle, three-quarter, over-shoulder;
- crop: close-up, medium close-up, half body;
- biểu cảm: lo lắng, suy tư, nhận ra, nhẹ nhõm, kiên định;
- tư thế tay và hành động: giữ sách, đặt sách xuống, nhìn lệch, chỉ vào ghi chú;
- đạo cụ phụ và bố trí background, nhưng không thay style.

Không lặp nguyên pose + camera + expression quá hai thumbnail liên tiếp. Mục tiêu là cùng nhận diện kênh nhưng không thành template-replicable content.

### 5b. LIKENESS / PRIVACY GATE

- Nhân vật trong ảnh là **nhân vật cartoon hư cấu lặp lại giữa các video** (cùng archetype bald cartoon figure của niche leader), không phải 岸見一郎 và không giống chính xác bất kỳ người thật nào.
- Không dùng prompt kiểu `portrait of Ichiro Kishimi`, face swap, exact likeness hoặc giả ông đang cầm/đọc/nói nội dung chưa từng thực hiện.
- Tên tác giả/tác phẩm chỉ xuất hiện trong phần attribution/source note hoặc text overlay biên tập; không tạo cảm giác endorsement.
- Sách/đạo cụ trong ảnh nền nên không có chữ đọc được; chữ Nhật được overlay thủ công để tránh sai chính tả và bìa sách giả.
- Vì là nhân vật cartoon hư cấu rõ ràng (không phải realistic synthetic imagery), không phát sinh yêu cầu khai báo Altered/Synthetic Content cho hình ảnh.

## 6. SCORING 100

```yaml
SCORE:
  tv_readability: 25          # TĂNG từ 15 (mobile_readability) — 69% imp từ TV
  instant_comprehension: 20
  emotional_specificity: 15
  curiosity_gap: 15
  title_complementarity: 15
  visual_conflict: 10
```

Chỉ chọn concept ≥80. Nếu không có, tạo lại. `title_complementarity` chấm thấp nếu thumbnail chỉ nhắc lại ý title (xem 4b).

**Điểm liệt (tự động FAIL bất kể tổng điểm):** `tv_readability` < 15, hoặc trượt bất kỳ số nào ở vòng 1 (mục 4a-1: copy > 11 ký tự, overlap > 35%, tương phản < 7:1). Vòng 2 (SQUINT TEST trên ảnh thật) là cổng chặn TRƯỚC KHI ĐĂNG, không phải cổng của bước này — trượt vòng 2 thì sửa rồi gen lại, không cần chạy lại toàn bộ skill.

Lưu ý `distinct_from_recent_thumbnails` (10đ ở v2.1) đã BỎ khỏi bảng điểm. Lý do: kênh chưa có thumbnail nào đạt CTR chấp nhận được, nên "khác với thumbnail gần đây" là ràng buộc vô nghĩa — khác với cái đang hỏng không phải là ưu điểm. Vẫn tránh lặp y hệt, nhưng không tính điểm cho nó cho tới khi có một thumbnail đạt CTR ≥4%.

## 7. OUTPUT

Với mỗi concept:

```yaml
THUMBNAIL_CONCEPT:
  mode:
  text:
  click_question:
  scene:
  subject:
  emotion:
  visual_conflict:
  title_complementarity:
  score:
```

Sau đó chọn một phương án và xuất:

```yaml
THUMBNAIL_CONTRACT:
  THUMBNAIL_TEXT_FINAL:
  THUMBNAIL_COPY_MODE:
  THUMBNAIL_EMOTION:
  THUMBNAIL_SCENE:
  FINAL_LAYOUT:
  WHY_THIS_CONCEPT:            # lý do chọn concept này (xem 3b)
  TITLE_THUMBNAIL_SPLIT:       # phân vai title/thumbnail + overlap_check (xem 4b)
  TV_READABILITY_CHECK:
    round1_copy_chars:         # số đo bằng code
    round1_title_overlap_pct:  # số đo bằng code
    round1_contrast_ratio:     # số đo bằng code, >= 7:1
    round1_verdict:            # PASS/FAIL
    round2_squint:             # PENDING_USER — Claude không được tự điền PASS (xem 4a-2)
  OPENING_MATCH_CHECK:
  IMAGE_PROMPT:                # prompt tiếng Anh, KHÔNG chữ trong ảnh — deliverable chính
  IMAGE_PROMPT_NEGATIVE:       # negative prompt
  TEXT_OVERLAY_SPEC:           # thông số để người dùng ghép chữ: nội dung, cỡ, màu, vị trí, khối nền
  AI_BAKED_TEXT_PROMPT_EXPERIMENTAL:   # tuỳ chọn — bản có chữ nướng sẵn, chỉ để thử
  USER_CHECKLIST_AFTER_GEN:    # các việc người dùng làm sau khi có ảnh (gồm SQUINT TEST vòng 2)
```

**`IMAGE_PROMPT` là deliverable chính của skill này.** Viết đủ 10 thành phần như `skill_tam_ly_hoc_image_production_JP` mục 2 (mục tiêu cảnh, chủ thể/hành động, biểu cảm, bối cảnh Nhật cụ thể, composition/shot, ánh sáng, palette, style anchor, continuity lock, negative). Chừa sẵn vùng trống cho khối chữ trong phần composition, vì chữ ghép sau.

`TEXT_OVERLAY_SPEC` phải ghi cụ thể để người dùng làm được mà không phải đoán: chuỗi chữ chính xác, số dòng, cỡ chữ theo % chiều cao khung, mã màu chữ, mã màu khối nền, vị trí khối (toạ độ tương đối), và độ dày font. Không ghi "chữ to, đậm, dễ đọc".

## 8. STYLE

Phong cách khóa theo ảnh mẫu của project: flat illustrated cartoon (giống niche leader PsychToons), thick black outline, solid flat colors, không gradient/shading, nền navy #1A2332. Không chuyển sang photorealistic/3D render/watercolor/pastel ở thumbnail. Prompt ảnh mặc định không chữ; text ghép thủ công theo overlay spec.

Mỗi thumbnail phải có điểm neo tương phản mạnh: headline vàng viền đen, khối phụ trắng hoặc vùng sáng/tối tách chủ thể. Khi mood và độ tương phản xung đột, ưu tiên tương phản.

## 9. GHI LẠI ĐỂ HỌC (bắt buộc)

Kênh đang thiếu dữ liệu về cái gì làm nên click. Mỗi thumbnail xuất bản phải ghi một dòng vào `thumbnail-history`:

```yaml
THUMBNAIL_HISTORY_ENTRY:
  video_id:
  concept_mode:            # SELF_RECOGNITION | CONTRADICTION | CONSEQUENCE_OR_RELIEF
  copy_text:
  copy_char_count:
  contrast_anchor:         # a | b | c (xem mục 8)
  has_face:                # true/false
  ctr_after_7d:            # điền sau, từ Reporting API
  impressions_after_7d:
```

Sau 3 thumbnail có dữ liệu CTR, đối chiếu để tìm cơ chế nào ăn — đó là cách duy nhất thoát khỏi phỏng đoán.
