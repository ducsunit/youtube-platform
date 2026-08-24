"""Commitment manifest — mọi cam kết định lượng/cấu trúc thành dữ liệu có schema.

Kiến trúc 3 lớp chống lỗi kiểu video-12 (title hứa "7つの" nhưng outline chỉ cấp 5):
  L1: planning phải kèm manifest cam kết (enumeration / factual_claim / promise)
      — LLM bị ép điền schema, con số nằm trong manifest chứ không trôi trong prose.
  L2: validator deterministic tự kiểm manifest (count == len(items), ledger_ref
      tồn tại, mọi con số trong title/psychological_job được cover) — fail EARLY
      ở narrative_brief thay vì chết ở script_audit sau khi tốn tiền viết script.
  L3: repair ladder có giới hạn — 1 lần sửa manifest + patch psychological_job
      (rẻ), hết cứu thì fail sớm với lý do rõ, không blind retry.

Manifest sống TRONG planning.json (`plan["commitments"]`) nên writer/auditor/
repair — mọi nơi đã nhận `plan` — tự động thấy nó mà không đổi chữ ký hàm.
"""
from __future__ import annotations

import json
import re
from typing import Any

COMMITMENT_TYPES = ("enumeration", "factual_claim", "promise")
CLAIM_FRAMINGS = ("sourced", "rhetorical")

# Regex mang tính GỢI Ý: chỉ để bảo đảm LLM không bỏ sót con số khi điền
# manifest — không phải whitelist pattern (kiến trúc này không chơi whack-a-mole).
_NUMERIC_HINT_RE = re.compile(
    r"(?:[一二三四五六七八九十百千〇\d]+\s*つ)"
    r"|\d+\s*%"
    r"|(?:[一二三四五六七八九十百千〇\d]+\s*(?:人|分|日|年|個|冊|章|倍|匹|件))"
)


def numeric_hints(topic: str, plan: dict) -> list[dict]:
    """Quét số xuất hiện ở title + psychological_job — nơi cam kết thường ẩn."""
    hints: list[dict] = []
    for match in _NUMERIC_HINT_RE.finditer(str(topic or "")):
        hints.append({"where": "topic", "text": match.group(0)})
    for section in (plan.get("sections") or []):
        if not isinstance(section, dict):
            continue
        job = str(section.get("psychological_job") or "")
        for match in _NUMERIC_HINT_RE.finditer(job):
            hints.append({"where": str(section.get("id") or "?"), "text": match.group(0)})
    return hints


_KANJI_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                 "六": 6, "七": 7, "八": 8, "九": 9}


def _parse_number(text: str) -> int | None:
    """'7つ'→7, '七つ'→7, '99%'→99, '1万人'→10000 — so khớp coverage theo GIÁ TRỊ
    thay vì chuỗi (七つ và 7つ là cùng một cam kết)."""
    match = re.search(r"\d+", text)
    if match:
        return int(match.group())
    total = 0
    num = 0
    seen = False
    for ch in text:
        if ch in _KANJI_DIGITS:
            num = _KANJI_DIGITS[ch]
            seen = True
        elif ch == "十":
            total += (num or 1) * 10
            num = 0
            seen = True
        elif ch == "百":
            total += (num or 1) * 100
            num = 0
            seen = True
        elif ch == "千":
            total += (num or 1) * 1000
            num = 0
            seen = True
    if not seen:
        return None
    return total + num


def _item_text(x: Any) -> str:
    """Item có thể là string hoặc dict ({item|text|label|name}: ...)."""
    if isinstance(x, dict):
        for key in ("item", "text", "label", "name", "point"):
            value = str(x.get(key) or "").strip()
            if value:
                return value
        return ""
    return str(x).strip() if x is not None else ""


def normalize_commitments(value: Any) -> list[dict]:
    """Ép output LLM về schema nghiêm; bỏ phần tử rác thay vì raise.

    LLM thỉnh thoảng tự sáng tạo type ("topic"...) hoặc trả items dạng dict —
    coerce về enumeration/factual_claim thay vì bỏ đi mất manifest hợp lệ.
    """
    rows = value.get("commitments") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        rows = value if isinstance(value, list) else []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("type") or "").strip().lower()
        if kind not in COMMITMENT_TYPES:
            # Coerce theo hình dạng dữ liệu thay vì bỏ.
            if isinstance(row.get("items"), list) or row.get("count") is not None:
                kind = "enumeration"
            elif row.get("value"):
                kind = "factual_claim"
            else:
                continue
        item: dict[str, Any] = {"type": kind}
        if kind == "enumeration":
            item["label"] = str(row.get("label") or row.get("text") or "").strip() or "enumeration"
            try:
                item["count"] = int(row.get("count"))
            except (TypeError, ValueError):
                items_probe = row.get("items") if isinstance(row.get("items"), list) else []
                if not items_probe:
                    continue
                item["count"] = len(items_probe)
            items = row.get("items") if isinstance(row.get("items"), list) else []
            item["items"] = [t for t in (_item_text(x) for x in items) if t]
            sections = row.get("sections") if isinstance(row.get("sections"), list) else []
            item["sections"] = [str(x).strip() for x in sections if str(x).strip()]
            # number_framing=symbolic: title nói "7つ" nhưng nguồn (claim ledger)
            # đóng khung con số là tượng trưng/điều hướng → script chỉ trình bày
            # số items thực tế có nguồn (count = len(items)), không bị ép đủ 7.
            framing = str(row.get("number_framing") or "").strip().lower()
            item["number_framing"] = framing if framing in ("exact", "symbolic") else "exact"
            if item["number_framing"] == "symbolic":
                item["note"] = str(row.get("note") or "").strip()[:300]
        elif kind == "factual_claim":
            item["value"] = str(row.get("value") or "").strip()
            framing = str(row.get("framing") or "").strip().lower()
            item["framing"] = framing if framing in CLAIM_FRAMINGS else "rhetorical"
            item["ledger_ref"] = str(row.get("ledger_ref") or "").strip()
            item["note"] = str(row.get("note") or "").strip()[:300]
        else:
            item["kind"] = str(row.get("kind") or "").strip()[:80]
            item["note"] = str(row.get("note") or "").strip()[:300]
        if item.get("value") or item.get("label") or item.get("kind"):
            out.append(item)
    return out


def _kanji_number(n: int) -> str:
    digits = "〇一二三四五六七八九"
    if n < 10:
        return digits[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return ("十" if tens == 1 else digits[tens] + "十") + (digits[ones] if ones else "")
    return str(n)


def validate_commitments(
    commitments: list[dict],
    plan: dict,
    hints: list[dict],
    ledger_text: str = "",
) -> list[str]:
    """Deterministic check trên MANIFEST (không phải prose). Trả danh sách lỗi."""
    issues: list[str] = []
    section_ids = {str(s.get("id")) for s in (plan.get("sections") or []) if isinstance(s, dict)}
    covered_hints: set[tuple[str, int | None]] = set()  # (text, giá trị số) đã cover
    seen_enum_labels: dict[str, int] = {}

    for row in commitments:
        if row["type"] == "enumeration":
            if not row.get("label"):
                issues.append("enumeration thiếu label")
                continue
            symbolic = row.get("number_framing") == "symbolic"
            if symbolic:
                # count = số items thực tế có nguồn; tự nhất quán vẫn bắt buộc
                row["count"] = len(row.get("items") or [])
            elif row.get("count", 0) < 2:
                issues.append("enumeration '%s': count phải ≥ 2" % row["label"])
            if len(row.get("items") or []) != row.get("count"):
                issues.append(
                    "enumeration '%s': count=%s nhưng items=%d — schema bắt buộc khớp"
                    % (row["label"], row.get("count"), len(row.get("items") or []))
                )
            bad_sections = [s for s in row.get("sections") or [] if s not in section_ids]
            if bad_sections:
                issues.append("enumeration '%s': sections không tồn tại: %s" % (row["label"], bad_sections))
            count_value = row.get("count")
            covered_for_row: list[int | None] = []
            for hint in hints:
                hint_value = _parse_number(hint["text"])
                if hint["text"] in str(row.get("label") or "") + "".join(row.get("items") or []):
                    covered_hints.add((hint["text"], hint_value))
                    covered_for_row.append(hint_value)
                elif count_value is not None and hint_value == count_value:
                    # 七つ và 7つ cùng giá trị — enumeration count đã cover
                    covered_hints.add((hint["text"], hint_value))
                    covered_for_row.append(hint_value)
                elif symbolic and (hint["where"] == "topic" or hint["where"] in (row.get("sections") or [])):
                    # nguồn đóng khung con số là tượng trưng → enumerate số items
                    # thực tế là đủ, không bị ép bằng số trong title
                    covered_hints.add((hint["text"], hint_value))
                    covered_for_row.append(hint_value)
            # Chống khai symbolic tùy tiện: phải có note căn cứ + ledger phải
            # nhắc số được tuyên bố là tượng trưng (hoặc chính label).
            if symbolic:
                if not row.get("note"):
                    issues.append(
                        "enumeration '%s': number_framing=symbolic cần note ghi rõ căn cứ ledger" % row["label"]
                    )
                elif ledger_text:
                    forms = [str(n) for n in covered_for_row if n]
                    forms += [_kanji_number(n) for n in covered_for_row if n]
                    forms.append(str(row.get("label") or ""))
                    if not any(f and f in ledger_text for f in forms):
                        issues.append(
                            "enumeration '%s': symbolic nhưng ledger không nhắc số nào trong %s — thiếu căn cứ"
                            % (row["label"], sorted({f for f in forms if f})[:5])
                        )
            # Trùng label với count khác nhau → mâu thuẫn nội bộ manifest
            label_key = row["label"].lower()
            if label_key in seen_enum_labels and seen_enum_labels[label_key] != row.get("count"):
                issues.append(
                    "enumeration '%s' xuất hiện 2 lần với count khác nhau (%s vs %s)"
                    % (row["label"], seen_enum_labels[label_key], row.get("count"))
                )
            seen_enum_labels[label_key] = row.get("count")
        elif row["type"] == "factual_claim":
            covered_hints.add((row.get("value") or "", _parse_number(row.get("value") or "")))
            if row.get("framing") == "sourced" and not row.get("ledger_ref"):
                issues.append("factual_claim '%s': framing=sourced nhưng thiếu ledger_ref" % row.get("value"))
            if row.get("framing") == "sourced" and ledger_text and row.get("ledger_ref") not in ledger_text:
                issues.append("factual_claim '%s': ledger_ref '%s' không có trong claim ledger"
                              % (row.get("value"), row.get("ledger_ref")))

    for hint in hints:
        if (hint["text"], _parse_number(hint["text"])) not in covered_hints:
            issues.append(
                "số '%s' (%s) chưa được commitment nào cover — hãy enumerate đủ, "
                "đánh dấu factual_claim (kèm ledger_ref), hoặc sửa psychological_job bỏ con số"
                % (hint["text"], hint["where"])
            )
    return issues


COMMITMENTS_SYSTEM = """Bạn là commitment auditor. Nhiệm vụ: trích xuất TẤT CẢ cam kết định lượng
và cấu trúc mà title + plan ngầm hứa với người xem, trả về JSON manifest duy nhất.
Chỉ trả JSON: {"commitments": [...]}
- type=enumeration: title/plan hứa liệt kê N mục (「Nつの…」) → liệt kê items cụ thể
  (lấy từ new_information/claim ledger/editorial_application của plan; không bịa nguồn mới).
  count PHẢI bằng đúng số phần tử items.
  + Nguồn hỗ trợ đủ N items → number_framing="exact".
  + Claim ledger đóng khung con số là tượng trưng/điều hướng (「象徴的なナビゲーション」
    「あくまで比喩」...) hoặc nguồn chỉ có ít hơn N items → number_framing="symbolic",
    count = số items thực tế có nguồn. Ghi rõ căn cứ vào "note".
  Ghi rõ sections nào sẽ trình bày.
- type=factual_claim: số liệu thực thế (%, số người...) → framing="sourced" kèm ledger_ref
  khi claim ledger hỗ trợ; nếu chỉ là ước lượng rhetorical thì framing="rhetorical".
- type=promise: lời hứa hình thức khác (đối tượng người xem, motif hình ảnh...).
Mọi con số trong topic/psychological_job PHẢI được cover bởi ít nhất một commitment."""


def extraction_prompt(topic: str, plan: dict, hints: list[dict]) -> str:
    return f"""TOPIC/TITLE:
{topic}

PLAN:
{json.dumps(plan, ensure_ascii=False)}

SỐ ĐÃ PHÁT HIỆN (bắt buộc cover hết, hoặc sửa psychological_job bỏ số nếu không phải cam kết thật):
{json.dumps(hints, ensure_ascii=False)}

Trả JSON manifest theo system. Nhớ: enumeration thì count == len(items)."""


COMMITMENTS_REPAIR_SYSTEM = """Bạn sửa commitment manifest bị validator chặn. CHỈ sửa đúng lỗi được liệt kê,
không thêm cam kết mới ngoài số đã phát hiện. Trả JSON:
{"commitments": [...manifest đầy đủ đã sửa...],
 "plan_patches": [{"section": "S5", "psychological_job": "..."}]}
- Con số nằm ở TITLE là cam kết với người xem: không bỏ được bằng plan_patches.
  Nếu claim ledger đóng khung số đó là tượng trưng/điều hướng → dùng
  number_framing="symbolic" (count = số items thực tế có nguồn, kèm note căn cứ).
  Nếu nguồn đủ N items → enumerate đủ N.
- Con số CHỈ nằm ở psychological_job và không phải cam kết thật → plan_patches
  viết lại job bỏ con số (giữ nguyên ý).
items của enumeration lấy từ new_information / claim ledger đã có, không bịa nguồn mới."""


def repair_prompt(plan: dict, commitments: list[dict], issues: list[str], hints: list[dict]) -> str:
    return f"""PLAN HIỆN TẠI:
{json.dumps(plan, ensure_ascii=False)}

MANIFEST BỊ CHẶN:
{json.dumps(commitments, ensure_ascii=False)}

CÁC LỖI VALIDATOR:
{json.dumps(issues, ensure_ascii=False, indent=1)}

SỐ CẦN COVER:
{json.dumps(hints, ensure_ascii=False)}

Sửa đúng các lỗi trên. Trả JSON theo system."""
