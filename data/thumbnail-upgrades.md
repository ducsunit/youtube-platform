# Nâng cấp Title + Thumbnail 7 video cũ — theo flow mới (mực đen + chalk-line figure)

> Style thumbnail: high-contrast black ink / off-white paper / 1 gold accent / headline vàng #FFE500
> Title grammar: hành vi cụ thể + câu hỏi + thuật ngữ (シャドウ・ペルソナ・課題の分離)
> Nguyên tắc: KHÔNG hứa số lượng mà nội dung không có (bài học commitment manifest)

## Kế hoạch update: 2 video/ngày × 4 ngày (ưu tiên view thấp trước)

Nguyên tắc: YouTube cần 2-3 ngày để đo lại CTR sau khi đổi — đổi 1-2 cái/ngày là tối đa
để đo được tác động; video view cao nhất đổi SAU CÙNG (ít rủi ro nhất khi style mới
chưa được kiểm chứng trên kênh mình).

| Ngày | Video | Views | Title # | Prompt file |
|---|---|---|---|---|
| Ngày 1 | bClYY9xpwX8 | 18 | #5 | `data/thumbnail-upgrades/2026-07-23_bClYY9xpwX8.txt` |
| Ngày 1 | n-xuwXpHFXU | 39 | #1 | `data/thumbnail-upgrades/2026-08-12_n-xuwXpHFXU.txt` |
| Ngày 2 | p0O3TEWLT-A | 35 | #2 | `data/thumbnail-upgrades/2026-08-10_p0O3TEWLT-A.txt` |
| Ngày 2 | G5eITKJf5eM | 47 | #3 | `data/thumbnail-upgrades/2026-08-09_G5eITKJf5eM.txt` |
| Ngày 3 | ddHmBDO7osY | 49 | #6 | `data/thumbnail-upgrades/2026-07-17_ddHmBDO7osY.txt` |
| Ngày 3 | OfP3DVdRdcc | 74 | #4 | `data/thumbnail-upgrades/2026-08-03_OfP3DVdRdcc.txt` |
| Ngày 4 | wYRtahxPtrU | 157 | #7 | `data/thumbnail-upgrades/2026-07-12_wYRtahxPtrU.txt` |

Sau mỗi đợt: chờ 48h xem CTR trong YouTube Studio (Analytics → Reach → Impressions CTR).
- CTR giữ hoặc tăng → tiếp tục kế hoạch
- CTR tụt >20% → rollback thumbnail cũ cho video đó, giữ title mới (tách biến số)

Lưu ý: đổi title + thumbnail CÙNG LÚC = đổi 2 biến; nếu muốn đo chuẩn thì đổi thumbnail
trước, title giữ nguyên 48h rồi mới đổi title. Nhưng với video <100 views thì rủi ro thấp,
đổi cùng lúc cho nhanh.

## File prompt từng video

- `data/thumbnail-upgrades/2026-08-12_n-xuwXpHFXU.txt` — 私のせい？
- `data/thumbnail-upgrades/2026-08-10_p0O3TEWLT-A.txt` — 断れない
- `data/thumbnail-upgrades/2026-08-09_G5eITKJf5eM.txt` — また反省会
- `data/thumbnail-upgrades/2026-08-03_OfP3DVdRdcc.txt` — ホッとした
- `data/thumbnail-upgrades/2026-07-23_bClYY9xpwX8.txt` — 大丈夫なふり
- `data/thumbnail-upgrades/2026-07-17_ddHmBDO7osY.txt` — 読みすぎた日
- `data/thumbnail-upgrades/2026-07-12_wYRtahxPtrU.txt` — なつかしいのに、つらい

Mỗi file là prompt hoàn chỉnh (dán thẳng vào gpt-image-2 / công cụ gen, khổ 2048x1152 rồi crop 16:9).

---


## Bảng tổng hợp

| # | Video | Title mới | Headline thumbnail |
|---|---|---|---|
| 1 | n-xuwXpHFXU | 【アドラー心理学】「私、何かした…？」他人の不機嫌まで背負って疲れる人へ――「課題の分離」の返し方 | 私のせい？ (giữ) |
| 2 | p0O3TEWLT-A | 【アドラー心理学】「断れない」のは優しさのせいじゃない――自分を削る「いい人」が境界線を引き直す方法 | 断れない (giữ) |
| 3 | G5eITKJf5eM | 【ユング心理学】夜になるとなぜか「あの時こうすればよかった」――一人反省会が止まらない本当の理由 | また反省会 (giữ) |
| 4 | OfP3DVdRdcc | 【アドラー心理学】予定がキャンセルされて「ホッとした」――その安堵は薄情じゃない。「課題の分離」が教える理由 | ホッとした (giữ) |
| 5 | bClYY9xpwX8 | 【ユング心理学】家に帰ると動けなくなるのは「怠け」じゃない――一日じゅう着ていた「ペルソナ」を外す時間 | 大丈夫なふり (mới) |
| 6 | ddHmBDO7osY | 【ユング心理学】人と会った後、どっと疲れる本当の理由――「空気を読む心」が抱える2つの見えない労働 | 読みすぎた日 (mới) |
| 7 | wYRtahxPtrU | 【ユング心理学】昔の友達に会うと、なぜ疲れるのか？――「関係の距離」に隠れたシャドウのサイン | なつかしいのに、つらい (mới) |

---

## 1. n-xuwXpHFXU — headline 「私のせい？」

Create exactly ONE finished 16:9 Japanese YouTube thumbnail, ready for a TV-grid view. Creative context only. Do NOT render the video title as text.

EDITORIAL INTENT: Title carries: the habit of carrying someone else's bad mood as your own fault, and how 課題の分離 gives it back. Thumbnail carries: the moment you notice you have tied someone else's dark mood to your own chest. The headline 「私のせい？」 is the exact self-question.

VISUAL STYLE: high-contrast black ink illustration, thick black outline, sparse hand-drawn brush texture, off-white paper field, black silhouettes, one controlled gold #FFD700 accent, 16:9. Full-bleed 16:9 symbolic ink tableau, one immediate emotional image. Reserve the top 24-30% for a single oversized Japanese headline, integrated through white paper or a soft ink fade — never a banner, hard split, panel, collage, or two backgrounds. Below it: one dominant psychological symbol and one clear human tension, readable in one second at TV-grid size.

CHARACTER CONTINUITY: keep one recurring fictional chalk-line figure — anonymous adult Japanese silhouette, off-white ink lines, round unfeatured head, restrained dot eyes only when emotion is needed, slim proportions, black charcoal clothing blocks. No identifiable real-person features, no second named figure.

SELECTED SCENE: the recurring chalk-line figure stands holding a heavy black ink cloud tied to their chest with a thin string — the cloud drifted from an off-frame silhouette at the edge of the paper. The string runs taut between them. On the floor near the figure's feet lies a small pair of ink-drawn scissors, untouched — the separation that exists but has not been used. The single gold #FFD700 accent: the scissors' handles. Paper texture fades softly; no hard split.

TEXT RENDERING: The Japanese headline 「私のせい？」 printed EXTRA LARGE and BOLD in bright lemon-GOLD #FFE500 kanji, Noto Sans JP Black / ultra-heavy rounded Gothic, tight tracking, 10-14px thick BLACK outline and subtle black shadow, one line across the upper 24-30% of the frame, fully readable from a TV grid. This is the ONLY readable text in the image. Do not render the video title, labels, captions, signs, or any other characters.

Negative: English letters, logo, banner, hard split, collage, panels, two backgrounds, blank upper half, photorealistic person, celebrity likeness, detailed anime character, multiple protagonists, busy crowd with faces, melodramatic crying, medical imagery, diagnosis imagery, glow, bevel, glossy 3D, colorful palette, more than one gold accent, gold clothing, clutter, low contrast, thin weak outlines, watermark, extra people with detail, distorted hands, deformed fingers, extra limbs, photorealistic, 3D render, readable labels, captions, signs, interface text, any text other than the exact headline.

---
## 2. p0O3TEWLT-A — headline 「断れない」

Create exactly ONE finished 16:9 Japanese YouTube thumbnail, ready for a TV-grid view. Creative context only. Do NOT render the video title as text.

EDITORIAL INTENT: Title carries: saying yes is not kindness — it is self-erasure, and the boundary line can be redrawn. Thumbnail carries: the moment of holding yet another request while your own plans quietly slip away. The headline 「断れない」 is the exact inability.

VISUAL STYLE: high-contrast black ink illustration, thick black outline, sparse hand-drawn brush texture, off-white paper field, black silhouettes, one controlled gold #FFD700 accent, 16:9. Full-bleed 16:9 symbolic ink tableau, one immediate emotional image. Reserve the top 24-30% for a single oversized Japanese headline, integrated through white paper or a soft ink fade — never a banner, hard split, panel, collage, or two backgrounds. Below it: one dominant psychological symbol and one clear human tension, readable in one second at TV-grid size.

CHARACTER CONTINUITY: keep one recurring fictional chalk-line figure — anonymous adult Japanese silhouette, off-white ink lines, round unfeatured head, restrained dot eyes only when emotion is needed, slim proportions, black charcoal clothing blocks. No identifiable real-person features, no second named figure.

SELECTED SCENE: the recurring chalk-line figure stands arms overloaded with stacked ink-drawn boxes — each box a request accepted — while one box tips and falls from the pile. Behind them, a single bold ink line is drawn across the floor like a boundary that stops mid-draw, unfinished. The single gold #FFD700 accent: one small empty box set safely apart from the pile — the thing they kept for themselves. Paper texture fades softly; no hard split.

TEXT RENDERING: The Japanese headline 「断れない」 printed EXTRA LARGE and BOLD in bright lemon-GOLD #FFE500 kanji, Noto Sans JP Black / ultra-heavy rounded Gothic, tight tracking, 10-14px thick BLACK outline and subtle black shadow, one line across the upper 24-30% of the frame, fully readable from a TV grid. This is the ONLY readable text in the image. Do not render the video title, labels, captions, signs, or any other characters.

Negative: English letters, logo, banner, hard split, collage, panels, two backgrounds, blank upper half, photorealistic person, celebrity likeness, detailed anime character, multiple protagonists, busy crowd with faces, melodramatic crying, medical imagery, diagnosis imagery, glow, bevel, glossy 3D, colorful palette, more than one gold accent, gold clothing, clutter, low contrast, thin weak outlines, watermark, extra people with detail, distorted hands, deformed fingers, extra limbs, photorealistic, 3D render, readable labels, captions, signs, interface text, any text other than the exact headline.

---
## 3. G5eITKJf5eM — headline 「また反省会」

Create exactly ONE finished 16:9 Japanese YouTube thumbnail, ready for a TV-grid view. Creative context only. Do NOT render the video title as text.

EDITORIAL INTENT: Title carries: the nightly one-person review meeting that replays and scores the day's conversations. Thumbnail carries: lying in bed while the day's words replay in a loop. The headline 「また反省会」 is the exact ritual.

VISUAL STYLE: high-contrast black ink illustration, thick black outline, sparse hand-drawn brush texture, off-white paper field, black silhouettes, one controlled gold #FFD700 accent, 16:9. Full-bleed 16:9 symbolic ink tableau, one immediate emotional image. Reserve the top 24-30% for a single oversized Japanese headline, integrated through white paper or a soft ink fade — never a banner, hard split, panel, collage, or two backgrounds. Below it: one dominant psychological symbol and one clear human tension, readable in one second at TV-grid size.

CHARACTER CONTINUITY: keep one recurring fictional chalk-line figure — anonymous adult Japanese silhouette, off-white ink lines, round unfeatured head, restrained dot eyes only when emotion is needed, slim proportions, black charcoal clothing blocks. No identifiable real-person features, no second named figure.

SELECTED SCENE: a sparse night bedroom in minimal ink. The recurring chalk-line figure lies on their side on the bed, dot eyes open, facing a looping circle of ink tape that floats above them — inside the loop, small blank speech bubbles repeat around the ring like a film reel of the day's conversations. The loop is closed everywhere except one thin gold #FFD700 crack — the single exit point from the loop. Paper texture fades softly; no hard split.

TEXT RENDERING: The Japanese headline 「また反省会」 printed EXTRA LARGE and BOLD in bright lemon-GOLD #FFE500 kanji, Noto Sans JP Black / ultra-heavy rounded Gothic, tight tracking, 10-14px thick BLACK outline and subtle black shadow, one line across the upper 24-30% of the frame, fully readable from a TV grid. This is the ONLY readable text in the image. Do not render the video title, labels, captions, signs, or any other characters.

Negative: English letters, logo, banner, hard split, collage, panels, two backgrounds, blank upper half, photorealistic person, celebrity likeness, detailed anime character, multiple protagonists, busy crowd with faces, melodramatic crying, medical imagery, diagnosis imagery, glow, bevel, glossy 3D, colorful palette, more than one gold accent, gold clothing, clutter, low contrast, thin weak outlines, watermark, extra people with detail, distorted hands, deformed fingers, extra limbs, photorealistic, 3D render, readable labels, captions, signs, interface text, any text other than the exact headline.

---
## 4. OfP3DVdRdcc — headline 「ホッとした」

Create exactly ONE finished 16:9 Japanese YouTube thumbnail, ready for a TV-grid view. Creative context only. Do NOT render the video title as text.

EDITORIAL INTENT: Title carries: feeling relief when a plan is cancelled is not coldness — 課題の分離 explains it. Thumbnail carries: the guilty relief the instant the cancellation notification arrives. The headline 「ホッとした」 is the exact feeling.

VISUAL STYLE: high-contrast black ink illustration, thick black outline, sparse hand-drawn brush texture, off-white paper field, black silhouettes, one controlled gold #FFD700 accent, 16:9. Full-bleed 16:9 symbolic ink tableau, one immediate emotional image. Reserve the top 24-30% for a single oversized Japanese headline, integrated through white paper or a soft ink fade — never a banner, hard split, panel, collage, or two backgrounds. Below it: one dominant psychological symbol and one clear human tension, readable in one second at TV-grid size.

CHARACTER CONTINUITY: keep one recurring fictional chalk-line figure — anonymous adult Japanese silhouette, off-white ink lines, round unfeatured head, restrained dot eyes only when emotion is needed, slim proportions, black charcoal clothing blocks. No identifiable real-person features, no second named figure.

SELECTED SCENE: the recurring chalk-line figure stands in a sparse room, shoulders dropping in visible relief, a long slow breath drawn as a single fading ink line from their lips. On the floor at their feet lies a smartphone seen from above, its screen showing only a large bold ink X mark — the cancellation — with no readable text. Behind the figure, a faint judging silhouette looms as a soft shadow, already dissolving into blank paper. The single gold #FFD700 accent: the X mark on the phone screen. Paper texture fades softly; no hard split.

TEXT RENDERING: The Japanese headline 「ホッとした」 printed EXTRA LARGE and BOLD in bright lemon-GOLD #FFE500 kanji, Noto Sans JP Black / ultra-heavy rounded Gothic, tight tracking, 10-14px thick BLACK outline and subtle black shadow, one line across the upper 24-30% of the frame, fully readable from a TV grid. This is the ONLY readable text in the image. Do not render the video title, labels, captions, signs, or any other characters.

Negative: English letters, logo, banner, hard split, collage, panels, two backgrounds, blank upper half, photorealistic person, celebrity likeness, detailed anime character, multiple protagonists, busy crowd with faces, melodramatic crying, medical imagery, diagnosis imagery, glow, bevel, glossy 3D, colorful palette, more than one gold accent, gold clothing, clutter, low contrast, thin weak outlines, watermark, extra people with detail, distorted hands, deformed fingers, extra limbs, photorealistic, 3D render, readable labels, captions, signs, interface text, any text other than the exact headline.

---
## 5. bClYY9xpwX8 — headline 「大丈夫なふり」

Create exactly ONE finished 16:9 Japanese YouTube thumbnail, ready for a TV-grid view. Creative context only. Do NOT render the video title as text.

EDITORIAL INTENT: Title carries: collapsing at home is not laziness — it is the moment the day-long persona (ペルソナ) comes off. Thumbnail carries: the exact second the front door closes and the "I'm fine" mask can finally be set down. The headline 「大丈夫なふり」 names the exact mask.

VISUAL STYLE: high-contrast black ink illustration, thick black outline, sparse hand-drawn brush texture, off-white paper field, black silhouettes, one controlled gold #FFD700 accent, 16:9. Full-bleed 16:9 symbolic ink tableau, one immediate emotional image. Reserve the top 24-30% for a single oversized Japanese headline, integrated through white paper or a soft ink fade — never a banner, hard split, panel, collage, or two backgrounds. Below it: one dominant psychological symbol and one clear human tension, readable in one second at TV-grid size.

CHARACTER CONTINUITY: keep one recurring fictional chalk-line figure — anonymous adult Japanese silhouette, off-white ink lines, round unfeatured head, restrained dot eyes only when emotion is needed, slim proportions, black charcoal clothing blocks. No identifiable real-person features, no second named figure.

SELECTED SCENE: a sparse Japanese entryway (genkan) in minimal ink. The recurring chalk-line figure sits on the floor with their back against the closed door, knees drawn up, head bowed — the body finally at rest. On a wall hook beside them hangs a second face-mask shaped like a calm smiling expression (the day's persona, taken off), drawn in heavier black, casting a long oversized shadow across the floor toward the figure. Faint dense hatch-marks beyond the door suggest the noisy world left behind. The single gold #FFD700 accent: a small warm lamp glow pooling around the figure's feet. Paper texture fades softly; no hard split.

TEXT RENDERING: The Japanese headline 「大丈夫なふり」 printed EXTRA LARGE and BOLD in bright lemon-GOLD #FFE500 kanji, Noto Sans JP Black / ultra-heavy rounded Gothic, tight tracking, 10-14px thick BLACK outline and subtle black shadow, one line across the upper 24-30% of the frame, fully readable from a TV grid. This is the ONLY readable text in the image. Do not render the video title, labels, captions, signs, or any other characters.

Negative: English letters, logo, banner, hard split, collage, panels, two backgrounds, blank upper half, photorealistic person, celebrity likeness, detailed anime character, multiple protagonists, busy crowd with faces, melodramatic crying, medical imagery, diagnosis imagery, glow, bevel, glossy 3D, colorful palette, more than one gold accent, gold clothing, clutter, low contrast, thin weak outlines, watermark, extra people with detail, distorted hands, deformed fingers, extra limbs, photorealistic, 3D render, readable labels, captions, signs, interface text, any text other than the exact headline.

---
## 6. ddHmBDO7osY — headline 「読みすぎた日」

Create exactly ONE finished 16:9 Japanese YouTube thumbnail, ready for a TV-grid view. Creative context only. Do NOT render the video title as text.

EDITORIAL INTENT: Title carries: the two invisible forms of work (reading expressions at high resolution + regulating your own feelings) that drain you after social time. Thumbnail carries: coming home after a day of reading every air current in the room. The headline 「読みすぎた日」 names the exact state.

VISUAL STYLE: high-contrast black ink illustration, thick black outline, sparse hand-drawn brush texture, off-white paper field, black silhouettes, one controlled gold #FFD700 accent, 16:9. Full-bleed 16:9 symbolic ink tableau, one immediate emotional image. Reserve the top 24-30% for a single oversized Japanese headline, integrated through white paper or a soft ink fade — never a banner, hard split, panel, collage, or two backgrounds. Below it: one dominant psychological symbol and one clear human tension, readable in one second at TV-grid size.

CHARACTER CONTINUITY: keep one recurring fictional chalk-line figure — anonymous adult Japanese silhouette, off-white ink lines, round unfeatured head, restrained dot eyes only when emotion is needed, slim proportions, black charcoal clothing blocks. No identifiable real-person features, no second named figure.

SELECTED SCENE: the recurring chalk-line figure sits alone at the frame edge, shoulders lowered, hands open and empty in their lap. Around them, the room's air is drawn as dozens of thin ink current-lines converging INTO the figure's chest like antennae receiving every signal — dense on the crowd side, fading to blank paper behind the figure, showing the emptiness after. Anonymous black silhouettes of a crowd appear only as faint background marks, no faces. One small speech bubble held closed inside the figure's hands carries the single gold #FFD700 accent — the unspoken word. Paper texture fades softly; no hard split.

TEXT RENDERING: The Japanese headline 「読みすぎた日」 printed EXTRA LARGE and BOLD in bright lemon-GOLD #FFE500 kanji, Noto Sans JP Black / ultra-heavy rounded Gothic, tight tracking, 10-14px thick BLACK outline and subtle black shadow, one line across the upper 24-30% of the frame, fully readable from a TV grid. This is the ONLY readable text in the image. Do not render the video title, labels, captions, signs, or any other characters.

Negative: English letters, logo, banner, hard split, collage, panels, two backgrounds, blank upper half, photorealistic person, celebrity likeness, detailed anime character, multiple protagonists, busy crowd with faces, melodramatic crying, medical imagery, diagnosis imagery, glow, bevel, glossy 3D, colorful palette, more than one gold accent, gold clothing, clutter, low contrast, thin weak outlines, watermark, extra people with detail, distorted hands, deformed fingers, extra limbs, photorealistic, 3D render, readable labels, captions, signs, interface text, any text other than the exact headline.

---
## 7. wYRtahxPtrU — headline 「なつかしいのに、つらい」

Create exactly ONE finished 16:9 Japanese YouTube thumbnail, ready for a TV-grid view. Creative context only. Do NOT render the video title as text.

EDITORIAL INTENT: Title carries: why meeting an old friend now feels exhausting, and the hidden "relationship distance" signal. Thumbnail carries: smiling warmly at an old friend while quietly counting the minutes. The headline 「なつかしいのに、つらい」 names the exact contradiction.

VISUAL STYLE: high-contrast black ink illustration, thick black outline, sparse hand-drawn brush texture, off-white paper field, black silhouettes, one controlled gold #FFD700 accent, 16:9. Full-bleed 16:9 symbolic ink tableau, one immediate emotional image. Reserve the top 24-30% for a single oversized Japanese headline, integrated through white paper or a soft ink fade — never a banner, hard split, panel, collage, or two backgrounds. Below it: one dominant psychological symbol and one clear human tension, readable in one second at TV-grid size.

CHARACTER CONTINUITY: keep one recurring fictional chalk-line figure — anonymous adult Japanese silhouette, off-white ink lines, round unfeatured head, restrained dot eyes only when emotion is needed, slim proportions, black charcoal clothing blocks. No identifiable real-person features, no second named figure.

SELECTED SCENE: a small café table in sparse ink. On the table lies one old photograph — the single warm gold #FFD700 accent in the frame. Across the table, the old friend is rendered as a faded half-erased ink silhouette, memory and present overlapping. On the near side, the recurring chalk-line figure smiles politely with dot eyes while one hand quietly grips the table edge; between the two figures a single long ink line stretches and thins like a measuring tape of distance. Paper texture fades softly; no hard split.

TEXT RENDERING: The Japanese headline 「なつかしいのに、つらい」 printed EXTRA LARGE and BOLD in bright lemon-GOLD #FFE500 kanji, Noto Sans JP Black / ultra-heavy rounded Gothic, tight tracking, 10-14px thick BLACK outline and subtle black shadow, one line across the upper 24-30% of the frame, fully readable from a TV grid. This is the ONLY readable text in the image. Do not render the video title, labels, captions, signs, or any other characters.

Negative: English letters, logo, banner, hard split, collage, panels, two backgrounds, blank upper half, photorealistic person, celebrity likeness, detailed anime character, multiple protagonists, busy crowd with faces, melodramatic crying, medical imagery, diagnosis imagery, glow, bevel, glossy 3D, colorful palette, more than one gold accent, gold clothing, clutter, low contrast, thin weak outlines, watermark, extra people with detail, distorted hands, deformed fingers, extra limbs, photorealistic, 3D render, readable labels, captions, signs, interface text, any text other than the exact headline.

---
