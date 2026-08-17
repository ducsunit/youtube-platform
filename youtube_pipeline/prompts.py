ANALYSIS_SYSTEM = (
    "Bạn là giám đốc chiến lược nội dung YouTube chuyên nghiệp. Dựa trên dữ liệu "
    "đầu vào của kênh, hãy đề xuất một ý tưởng video tiếp theo tối ưu. Kết quả bắt "
    "buộc là JSON đúng schema được yêu cầu."
)

WRITER_SYSTEM = (
    "Bạn là nhà biên kịch YouTube kỳ cựu. Viết lời kể lôi cuốn, đời thường, tự nhiên "
    "và có tính điện ảnh. Tránh ngôn ngữ sáo rỗng hoặc mang dấu ấn văn mẫu AI."
)

REVIEW_SYSTEM = """Bạn là chuyên gia tối ưu kịch bản YouTube theo các nguyên tắc giữ chân người xem.
Bắt buộc:
1. Hook trong 3 giây đầu phải tạo khoảng trống tò mò; không chào hỏi dài dòng.
2. Nhịp độ phải mạch lạc; cắt câu lặp, sáo rỗng và các đoạn chuyển lê thê.
3. Giải quyết đầy đủ lời hứa của tiêu đề, không dùng clickbait sai lệch.
Tinh chỉnh trực tiếp bản nháp nhưng không thay đổi cốt truyện và sự kiện gốc.
Chỉ trả về JSON đúng schema được yêu cầu."""

AUDIT_SYSTEM = """Bạn là kiểm toán viên độc lập về tính nhất quán nội dung.
Bạn KHÔNG viết lại kịch bản và KHÔNG tự bổ sung kiến thức bên ngoài.
Chỉ đối chiếu dữ liệu nguồn, proposal, bản nháp và bản final được cung cấp.
Thông tin cụ thể trong bản final không có căn cứ trong các dữ liệu trên phải được liệt kê là unsupported_claim.
Mọi thay đổi về tên riêng, con số, mốc thời gian, quan hệ nhân quả hoặc kết luận phải được kiểm tra nghiêm ngặt.
Chỉ trả về JSON đúng schema, không kèm giải thích bên ngoài JSON."""

REPAIR_SYSTEM = """Bạn là biên tập viên sửa lỗi nhất quán.
Chỉ sửa các lỗi được auditor hoặc quality gate chỉ ra.
Không thêm dữ kiện mới, không thay đổi cốt truyện và không xóa các ý bắt buộc trong dàn ý.
Chỉ trả về JSON đúng schema được yêu cầu."""


def analysis_prompt(raw_data: str) -> str:
    return f"""Dữ liệu thô đầu vào của kênh YouTube:
{raw_data}

Phân tích và chỉ trả về JSON theo schema:
{{
  "suggested_title": "Tiêu đề cuốn hút nhưng trung thực",
  "target_duration": "Thời lượng mục tiêu",
  "script_outline": "Dàn ý chi tiết, định lượng theo từng mốc thời gian"
}}"""


def writer_prompt(title: str, duration: str, outline: str) -> str:
    return f"""Viết kịch bản chi tiết theo kế hoạch sau:
- Tiêu đề: {title}
- Thời lượng mục tiêu: {duration}
- Dàn ý bắt buộc:
{outline}

Viết đầy đủ lời thoại, chia rõ các phần theo dòng thời gian và giữ logic của dàn ý."""


def review_prompt(title: str, duration: str, outline: str, draft: str) -> str:
    return f"""--- DỮ LIỆU ĐỐI CHIẾU ---
Tiêu đề: {title}
Thời lượng: {duration}
Dàn ý: {outline}

--- BẢN NHÁP ---
{draft}

Tối ưu bản nháp và chỉ trả về JSON theo schema:
{{
  "optimization_report": "Tóm tắt ngắn gọn các thay đổi",
  "final_script": "Toàn bộ kịch bản hoàn chỉnh"
}}"""


def audit_prompt(
    auditor_name: str,
    raw_data: str,
    title: str,
    duration: str,
    outline: str,
    draft: str,
    final_script: str,
) -> str:
    return f"""AUDITOR: {auditor_name}

--- DỮ LIỆU NGUỒN BẤT BIẾN ---
{raw_data}

--- PROPOSAL GỐC ---
Tiêu đề: {title}
Thời lượng: {duration}
Dàn ý: {outline}

--- BẢN NHÁP DEEPSEEK ---
{draft}

--- KỊCH BẢN FINAL CẦN KIỂM TRA ---
{final_script}

Đối chiếu từng claim và chỉ trả về JSON theo schema:
{{
  "overall_score": 0,
  "decision": "pass hoặc revise",
  "outline_coverage": true,
  "title_alignment": true,
  "duration_alignment": true,
  "contradictions": ["Mỗi mâu thuẫn cụ thể, để [] nếu không có"],
  "unsupported_claims": ["Mỗi claim không có căn cứ, để [] nếu không có"],
  "missing_outline_points": ["Mỗi ý dàn bài bị thiếu, để [] nếu không có"],
  "claim_checks": [
    {{
      "claim_id": "C001",
      "final_claim": "Claim cụ thể trích từ bản final",
      "source_evidence": "Đoạn đối chiếu chính xác; để chuỗi rỗng nếu không có",
      "status": "supported, contradiction hoặc unsupported",
      "explanation": "Giải thích ngắn gọn kết quả đối chiếu"
    }}
  ],
  "summary": "Kết luận ngắn gọn có dẫn chứng"
}}

Phải trích xuất và kiểm tra từng claim có thể xác minh trong bản final vào claim_checks.
Chỉ đặt decision là pass khi mọi claim đều supported, không có mâu thuẫn, claim thiếu nguồn hoặc ý dàn bài bị thiếu; đồng thời tiêu đề, thời lượng và toàn bộ dàn ý đều khớp."""


def repair_prompt(
    raw_data: str,
    title: str,
    duration: str,
    outline: str,
    draft: str,
    final_script: str,
    audit_findings: str,
) -> str:
    return f"""--- DỮ LIỆU NGUỒN BẤT BIẾN ---
{raw_data}

--- PROPOSAL GỐC ---
Tiêu đề: {title}
Thời lượng: {duration}
Dàn ý: {outline}

--- BẢN NHÁP GỐC ---
{draft}

--- KỊCH BẢN FINAL HIỆN TẠI ---
{final_script}

--- LỖI CẦN SỬA ---
{audit_findings}

Sửa đúng các lỗi được nêu và trả về JSON:
{{
  "optimization_report": "Tóm tắt chính xác các lỗi đã sửa",
  "final_script": "Toàn bộ kịch bản sau khi sửa"
}}"""
