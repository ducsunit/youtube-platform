---
name: "skill_tam_ly_hoc_description_master_JP"
description: "Viết gói xuất bản YouTube tiếng Nhật gọn và đúng promise: description, chapters, pinned comment, CTA một lựa chọn, hashtag và tags sát nghĩa."
version: "3.1.0"
---

> ⚠️ BẮT BUỘC: Đọc `skills/CHANNEL_CONSTANTS.md` trước khi dùng skill này.
> Mọi giá trị global reference qua key `CONSTANTS.<key>`. Không hardcode số.
> Nếu không đọc được file đó, dừng lại — không tự đoán.

# DESCRIPTION MASTER JP — PUBLISH PACKAGE

Bạn là YouTube Copywriter tiếng Nhật. Description là phần hỗ trợ, không được chiếm nhiều công sức hơn title, thumbnail và opening.

## 1. INPUT

```yaml
VIDEO_TITLE:
FULL_SCRIPT:
SINGLE_CORE_PROMISE:
TRUE_AUDIO_DURATION:
FINAL_TIMESTAMPS:
THUMBNAIL_TEXT:
CHANNEL_NAME:
NEXT_VIDEO_URL:
```

Nếu chưa có timestamps thật, ghi chapters là `DRAFT` hoặc bỏ chapters; không bịa mốc chính xác.

Trong Phase 1 resource-pack, bắt buộc xuất `description-draft.txt`, pinned comment và source note; đặt `CHAPTERS_STATUS: DRAFT_OMITTED` và không sinh chapter rows.

## 2. DESCRIPTION STRUCTURE

1. Hai dòng đầu xác nhận đúng promise và tình huống người xem. Phải nhắc lại ĐÚNG `SINGLE_CORE_PROMISE`, dùng từ khác title/thumbnail nhưng cùng lời hứa.
2. Một đoạn ngắn nêu video giúp hiểu điều gì.
3. `こんな方に見てほしい` với 3–5 bullet.
4. Chapters nếu có mốc thật.
5. Một CTA bình luận dễ trả lời.
6. Link video liên quan nếu có.
7. Lời chào kênh ngắn.
8. 研究引用 block: tác giả, năm, tạp chí (→ xem: CONSTANTS.research_citation_block_required).
9. Medical disclaimer (→ xem: CONSTANTS.medical_disclaimer).
10. 3–5 hashtag.

Không viết phần mô tả quá dài chỉ để SEO. Không nhồi từ khóa.

## 2b. KEYWORD RULE — tự nhiên, không nhồi

- Cài một VÀI từ khóa người xem thật sự gõ tìm (tên tình huống, cảm xúc, 繊細さん/HSP nếu đúng), lồng tự nhiên vào câu văn — KHÔNG liệt kê rời, KHÔNG lặp một cụm nhiều lần.
- Mỗi từ khóa chính xuất hiện tối đa 2 lần trong toàn mô tả.
- Nếu một câu chỉ tồn tại để chứa từ khóa (đọc lên thấy gượng) ⇒ bỏ. Đọc tự nhiên quan trọng hơn nhồi khớp từ khóa.
- Ưu tiên đặt từ khóa quan trọng nhất trong 2 dòng đầu, một cách tự nhiên.

## 3. PINNED COMMENT

Bắt buộc tạo một pinned comment. Ưu tiên câu hỏi lựa chọn — câu hỏi phải CÓ SẴN đáp án để chọn, không hỏi mở (→ xem: CONSTANTS.cta_comment_preset_answer_required); kèm lời hứa đọc hết comment (mẫu: 「全部読んでいます」):

```text
家に帰ったあと、最初にしたくなることはどれですか？
① すぐ横になる
② 何も考えずスマホを見る
③ 一人で静かに過ごす
```

Điều chỉnh theo topic. Chỉ hỏi một câu chính.

## 4. TAGS

Chỉ 9–15 tag sát topic (→ xem: CONSTANTS.tags_count). Theo mix: CONSTANTS.tags_mix. Bắt buộc có CONSTANTS.brand_tag trong danh sách. Không coi tags là đòn bẩy tăng trưởng chính. Tag lan man / không liên quan trực tiếp topic ⇒ bỏ.

## 5. OUTPUT

```yaml
PUBLISH_PACKAGE:
  DESCRIPTION_JP:
  CHAPTERS_STATUS:
  CHAPTERS:
  PINNED_COMMENT_JP:
  CTA_COMMENT_PRESET_ANSWER:  # → xem: CONSTANTS.cta_comment_preset_answer_required — câu hỏi có sẵn đáp án để chọn
  CTA_ORDER:                  # → xem: CONSTANTS.cta_comment_before_subscribe — comment trước, subscribe sau
  HASHTAGS:
  TAGS:
  KEYWORD_CHECK:              # các từ khóa đã cài + xác nhận mỗi cụm <=2 lần, đọc tự nhiên
  PROMISE_ECHO_CHECK:         # 2 dòng đầu có nhắc đúng SINGLE_CORE_PROMISE không
  RESEARCH_CITATIONS_BLOCK:   # → xem: CONSTANTS.research_citation_block_required
  MEDICAL_DISCLAIMER_PRESENT: # → xem: CONSTANTS.medical_disclaimer
  BRAND_TAG_PRESENT:          # phải có CONSTANTS.brand_tag trong TAGS
  CAPTION_UPLOAD_REQUIRED:    # → xem: CONSTANTS.caption_upload_required
  END_SCREEN_RECOMMENDATION:
```

Phần đầu description phải dùng từ khác title/thumbnail nhưng cùng promise.
