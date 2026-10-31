"""P4.1 retrieval dataset — tài liệu VI+EN do CHÚNG TA soạn (không tài liệu bên thứ ba).

Mục đích: đo retrieval (Recall@K, MRR), citation validity và latency trên corpus
nhỏ có ground truth page/chunk. Corpus là văn bản tự soạn về kiến thức máy tính
cơ bản — **không** chứa tài liệu riêng, không chép nội dung có bản quyền.

Mỗi tài liệu gồm các trang, mỗi trang vài đoạn. Ground truth của câu hỏi được
gán bằng `(doc_id, page)` — ổn định hơn chunk_index vì chunking là chi tiết
implementation. Retrieval đúng nếu trả về chunk cùng doc + page.

Bộ câu hỏi chia 2 nhóm ngôn ngữ (vi/en) và gồm:
  - câu hỏi paraphrase (không trùng nguyên văn) ⇒ thử thách vector branch;
  - câu hỏi tiếng Việt không dấu ⇒ kiểm fold dấu;
  - câu hỏi ngoài phạm vi ⇒ đo abstention (kỳ vọng `insufficientEvidence`).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalDocument:
    id: str
    title: str
    language: str
    pages: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "language": self.language,
            "pages": list(self.pages),
        }


@dataclass(frozen=True)
class EvalQuery:
    id: str
    query: str
    language: str
    # Ground truth: (doc_id, page_number). Rỗng ⇒ kỳ vọng ABSTAIN.
    expect: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    notes: str = ""

    @property
    def should_abstain(self) -> bool:
        return not self.expect

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "query": self.query,
            "language": self.language,
            "expect": [{"docId": d, "page": p} for d, p in self.expect],
            "notes": self.notes,
        }


DOCUMENTS: tuple[EvalDocument, ...] = (
    EvalDocument(
        id="vi-python-basics",
        title="Nhập môn Python",
        language="vi",
        pages=(
            "Python là ngôn ngữ thông dịch, cú pháp rõ ràng và dễ đọc. Biến trong "
            "Python không cần khai báo kiểu dữ liệu tường minh. Các kiểu cơ bản gồm "
            "số nguyên, số thực, chuỗi và giá trị luận lý.",
            "Vòng lặp for duyệt qua một tập hợp như danh sách hoặc chuỗi. Vòng lặp "
            "while lặp lại chừng nào điều kiện còn đúng, nên cần thay đổi biến điều "
            "kiện trong thân vòng lặp để tránh lặp vô hạn.",
            "Hàm được khai báo bằng từ khoá def. Tham số mặc định giúp gọi hàm gọn "
            "hơn. Một hàm có thể trả về nhiều giá trị dưới dạng bộ tuple.",
        ),
    ),
    EvalDocument(
        id="vi-data-structures",
        title="Cấu trúc dữ liệu căn bản",
        language="vi",
        pages=(
            "Ngăn xếp hoạt động theo nguyên tắc vào sau ra trước. Hai thao tác chính "
            "là đẩy vào đỉnh và lấy ra khỏi đỉnh, đều có độ phức tạp hằng số.",
            "Hàng đợi hoạt động theo nguyên tắc vào trước ra trước. Hàng đợi hai "
            "đầu cho phép thêm và lấy phần tử ở cả hai phía.",
            "Cây nhị phân tìm kiếm giữ bất biến mọi khoá bên trái nhỏ hơn khoá gốc "
            "và mọi khoá bên phải lớn hơn. Bất biến này cho phép tìm kiếm nhanh.",
        ),
    ),
    EvalDocument(
        id="en-databases",
        title="Relational Databases",
        language="en",
        pages=(
            "A relational database stores rows in tables and enforces constraints "
            "such as primary keys and foreign keys. A primary key uniquely identifies "
            "each row in a table.",
            "Normalization reduces redundancy by splitting data into related tables. "
            "Third normal form removes transitive dependencies between non-key "
            "attributes.",
            "An index speeds up reads at the cost of slower writes. A B-tree index "
            "supports equality and range queries efficiently.",
        ),
    ),
    EvalDocument(
        id="en-networking",
        title="Networking Fundamentals",
        language="en",
        pages=(
            "TCP provides reliable, ordered delivery using acknowledgements and "
            "retransmission. UDP does not guarantee delivery and has lower overhead.",
            "DNS resolves human readable domain names into IP addresses. Caching "
            "reduces lookup latency but can serve stale records until the "
            "time-to-live expires.",
            "TLS establishes an encrypted channel using a handshake that negotiates "
            "cipher suites and verifies the server certificate.",
        ),
    ),
)

QUERIES: tuple[EvalQuery, ...] = (
    # ---- VI: trùng từ khoá rõ ràng
    EvalQuery("vi-py-1", "vòng lặp while cần thay đổi gì để tránh lặp vô hạn", "vi", (("vi-python-basics", 2),)),
    EvalQuery("vi-py-2", "kiểu dữ liệu cơ bản trong Python gồm những gì", "vi", (("vi-python-basics", 1),)),
    EvalQuery("vi-ds-1", "ngăn xếp hoạt động theo nguyên tắc nào", "vi", (("vi-data-structures", 1),)),
    EvalQuery("vi-ds-2", "cây nhị phân tìm kiếm giữ bất biến gì", "vi", (("vi-data-structures", 3),)),
    # ---- VI paraphrase (không trùng nguyên văn)
    EvalQuery(
        "vi-py-para",
        "làm sao để không bị treo mãi trong một vòng lặp điều kiện",
        "vi",
        (("vi-python-basics", 2),),
        notes="paraphrase: không dùng cụm 'while'/'vô hạn'",
    ),
    EvalQuery(
        "vi-ds-para",
        "cấu trúc nào lấy phần tử ra theo thứ tự ngược với lúc thêm vào",
        "vi",
        (("vi-data-structures", 1),),
        notes="paraphrase của LIFO",
    ),
    # ---- VI không dấu (fold diacritics)
    EvalQuery("vi-nodiacritic-1", "ngan xep vao sau ra truoc", "vi", (("vi-data-structures", 1),)),
    EvalQuery("vi-nodiacritic-2", "ham tra ve nhieu gia tri", "vi", (("vi-python-basics", 3),)),
    # ---- EN
    EvalQuery("en-db-1", "what does a primary key uniquely identify", "en", (("en-databases", 1),)),
    EvalQuery("en-db-2", "which normal form removes transitive dependencies", "en", (("en-databases", 2),)),
    EvalQuery("en-db-3", "why does an index slow down writes", "en", (("en-databases", 3),)),
    EvalQuery("en-net-1", "difference between TCP and UDP delivery guarantees", "en", (("en-networking", 1),)),
    EvalQuery("en-net-2", "how does DNS caching cause stale records", "en", (("en-networking", 2),)),
    EvalQuery("en-net-3", "what does the TLS handshake verify", "en", (("en-networking", 3),)),
    # ---- ABSTAIN (ngoài phạm vi corpus)
    EvalQuery("abstain-1", "công thức nấu phở bò gia truyền", "vi", (), notes="không có trong tài liệu"),
    EvalQuery("abstain-2", "how to file a patent in Europe", "en", (), notes="không có trong tài liệu"),
)


def dataset_summary() -> dict:
    return {
        "documents": len(DOCUMENTS),
        "pages": sum(len(doc.pages) for doc in DOCUMENTS),
        "queries": len(QUERIES),
        "answerable": sum(1 for q in QUERIES if not q.should_abstain),
        "abstain": sum(1 for q in QUERIES if q.should_abstain),
        "languages": sorted({q.language for q in QUERIES}),
    }


def get_queries(language: str | None = None) -> tuple[EvalQuery, ...]:
    if language:
        return tuple(q for q in QUERIES if q.language == language)
    return QUERIES
