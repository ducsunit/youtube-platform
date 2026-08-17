# HÀNG ĐỢI 10 VIDEO TIẾP THEO — こころ包み

Dữ liệu nội dung — nguồn: `kokorotsutsumi-checklist.md` mục H. Skill `seri` lấy topic theo thứ
tự queue; sau khi đăng, cập nhật `status` và ghi cơ chế đã dùng vào nhật ký cuối file.

**Quy tắc:**
- Title trong queue là **working title** — title thật phải qua `TITLE_LOCK` của script_master.
- Cơ chế gợi ý chỉ là gợi ý — seri chốt thật sau khi chạy gate `mechanism_diversity`
  (→ `CONSTANTS.mechanism_diversity_window`) với lịch sử đăng thật.
- Mỗi topic vẫn phải qua NICHE CORE GATE + TOPIC DISTANCE GATE của seri bình thường.

## Bảng tổng quan

| # | Hiện tượng | primary_core | Cơ chế chính | Cơ chế dự phòng | Frame văn hóa | Status |
|---|---|---|---|---|---|---|
| 1 | Im lặng khi bị tổn thương | ne_tranh | 愛着スタイル (avoidant) | 学習性無力感 | 本音 | in_progress |
| 2 | Không thể từ chối | kiet_suc | 認知的不協和 | 愛着スタイル (anxious) | 空気を読む | queued |
| 3 | Thích ở một mình | ne_tranh | HSP | — | 侘寂 | in_progress |
| 4 | Đứa trẻ "lạc loài" trong nhà | kiet_suc | 学習性無力感 | 愛着スタイル | 建前/本音 | queued |
| 5 | Đọc không khí quá mức | kiet_suc | 感情労働 | — | 空気を読む | queued |
| 6 | Tử tế với mọi người trừ bản thân | kiet_suc | 愛着スタイル (anxious) | 学習性無力感 | 甘え | queued |
| 7 | Phiên tự kiểm điểm ban đêm | nhai_lai | 反芻思考 | — | 侘寂 | queued |
| 8 | Lặng lẽ rời đi thay vì tranh luận | ne_tranh | 愛着スタイル (avoidant) | 学習性無力感 | 空気を読む | queued |
| 9 | Mệt ngay khi đóng cửa nhà | kiet_suc | 感情労働 | HSP | 建前/本音 | queued |
| 10 | Thôi kỳ vọng vào người khác | nhai_lai | 学習性無力感 | 認知的不協和 | 甘え | queued |

## Chi tiết từng video

### 1. Người im lặng khi bị tổn thương
- **working_title_jp:** 傷ついた時、黙ってしまう人の心理
- **central_emotion:** 言いたいのに言えない — 飲み込んだ言葉の重さ
- **mechanism:** 愛着スタイル, kiểu avoidant (→ `content/mechanisms.md` mục 5)
- **backup_mechanism:** 学習性無力感 ("nói ra cũng vô ích") — nếu diversity gate chạm
- **cultural_frame:** 本音 (giữ nỗi đau bên trong)
- **notes:** checklist mục D đã có title mẫu hoàn chỉnh cho topic này — ưu tiên tham chiếu.

### 2. Người không thể từ chối
- **working_title_jp:** 断れない人の心理
- **central_emotion:** 断りたいのに笑って受ける — khoảnh khắc hối hận ngay sau đó
- **mechanism:** 認知的不協和 (→ `content/mechanisms.md` mục 4)
- **cultural_frame:** 空気を読む (từ chối = phá không khí)
- **notes:** từ khóa `断れない` nằm trong `CONSTANTS.title_keywords_jp`.

### 3. Người thích ở một mình
- **working_title_jp:** 一人が好きな人の心理
- **central_emotion:** 一人の時間が終わるときの、名残惜しさと安堵
- **mechanism:** HSP (→ `content/mechanisms.md` mục 2)
- **cultural_frame:** 侘寂 (một mình không phải thiếu sót)
- **notes:** từ khóa HSP + 一人が好き trong `CONSTANTS.title_keywords_jp`; cẩn thận KHÔNG trấn an kiểu "bạn không cô đơn đâu" sớm — giữ xá tội sau phút 5.

### 4. Đứa trẻ "lạc loài" trong nhà
- **working_title_jp:** 家族の中で「浮いていた子」の心理
- **central_emotion:** 家族の中で、いつも一人だけズレている感覚
- **mechanism:** 学習性無力感 (cố hòa nhập, thất bại lặp lại, rồi thôi cố) (→ `content/mechanisms.md` mục 6)
- **cultural_frame:** 建前/本音 (gia đình Nhật — hòa thuận bề mặt)
- **notes:** checklist mục D có title mẫu hoàn chỉnh; khớp công thức title `家族の中で〜だった子`.

### 5. Người đọc không khí quá mức
- **working_title_jp:** 空気を読みすぎる人の心理
- **central_emotion:** その場の空気を、自分の背中で背負ってしまう感覚
- **mechanism:** 感情労働 (→ `content/mechanisms.md` mục 1)
- **cultural_frame:** 空気を読む
- **notes:** bước 7 (quy tội hệ thống) dùng đúng mẫu câu checklist mục A: 「空気を読める人ほど損をする環境…」.

### 6. Người tử tế với mọi người trừ bản thân
- **working_title_jp:** 他人に優しく、自分に厳しい人の心理
- **central_emotion:** 人には優しくできるのに、自分にだけ容赦がない
- **mechanism:** 愛着スタイル, kiểu anxious (đổi kiểu so với #1 — cho đi để được giữ lại) (→ `content/mechanisms.md` mục 5)
- **backup_mechanism:** 学習性無力感 — nếu diversity gate chạm vì #1/#8
- **cultural_frame:** 甘え (không dám nhận chăm sóc ngược lại)
- **notes:** một video chỉ sâu MỘT kiểu attachment — ghi rõ trong SCRIPT_CONTRACT.

### 7. Phiên tự kiểm điểm ban đêm
- **working_title_jp:** 夜、昨日の会話を反芻してしまう人の心理
- **central_emotion:** 夜、昨日の会話が頭から離れない
- **mechanism:** 反芻思考 (→ `content/mechanisms.md` mục 3)
- **cultural_frame:** 侘寂 (buông điều không sửa được)
- **notes:** video đầu tiên chạm sâu lõi `nhai_lai` — phân biệt rõ rumination vs reflection (suy nghĩ có ích).

### 8. Người lặng lẽ rời đi thay vì tranh luận
- **working_title_jp:** 喧嘩せず、静かに去る人の心理
- **central_emotion:** 言い返せたはずの一言を、何年も持ち歩いている
- **mechanism:** 愛着スタイル, kiểu avoidant (→ `content/mechanisms.md` mục 5)
- **backup_mechanism:** 学習性無力感 ("tranh luận cũng vô ích") — nếu diversity gate chạm
- **cultural_frame:** 空気を読む (tránh phá vỡ không khí)
- **notes:** cùng họ hiện tượng với #1 (cách 7 video) — bắt buộc đổi tình huống kích hoạt và câu xá tội; nếu #6 đã dùng attachment trong 3 video gần nhất thì chuyển sang backup.

### 9. Người mệt ngay khi đóng cửa nhà
- **working_title_jp:** 家に帰った瞬間、どっと疲れる人の心理
- **central_emotion:** 玄関の鍵を閉めた瞬間に、崩れ落ちる疲れ
- **mechanism:** 感情労働 (diễn cả ngày, về nhà thôi diễn thì sụp) (→ `content/mechanisms.md` mục 1)
- **backup_mechanism:** HSP (overstimulation) — nếu #5 đã dùng 感情労働 trong 3 video gần nhất
- **cultural_frame:** 建前/本音
- **notes:** ⚠️ V3 đã đăng góc này (外では平気なのに、家に帰ると…) — bắt buộc đổi tình huống kích hoạt (vd: cả ngày bình thường, nhưng chạm tay nắm cửa là nước mắt trào).

### 10. Người thôi kỳ vọng vào người khác
- **working_title_jp:** 人に期待しなくなった人の心理
- **central_emotion:** 期待するのをやめたあと、胸に残る静かな諦め
- **mechanism:** 学習性無力感 (→ `content/mechanisms.md` mục 6)
- **backup_mechanism:** 認知的不協和 — nếu #4 đã dùng 学習性無力感 trong 3 video gần nhất
- **cultural_frame:** 甘え (kỳ vọng ≠ yếu đuối; kỳ vọng lành mạnh là kỹ năng, không phải điểm yếu)
- **notes:** tránh nhắc 課題の分離 làm dẫn chứng chính (cơ chế đã dùng 3/7 video cũ — ⛔ trong `content/mechanisms.md`).

---

## Rule re-cut sau 30 ngày

Sau 30 ngày kể từ video đầu của queue: tìm video **nổi nhất** (view + retention), rồi cắt lại
chủ đề đó **2–3 lần với cơ chế KHÁC mỗi lần** — PsychToons làm 3 video "im lặng khi bị tổn
thương", bản đầu 2.36M view. Không re-cut trước 30 ngày: chưa đủ dữ liệu để biết video nào
thật sự nổi.

## Nhật ký dùng (cập nhật sau mỗi lần đăng)

| Ngày đăng | Video (queue #) | Cơ chế đã dùng | Frame đã dùng | Video ID |
|---|---|---|---|---|
| — | (chưa có video queue nào đăng) | — | — | — |
