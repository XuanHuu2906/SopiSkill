# 19 — Learning Design, DAG Curriculum & AI Evaluation Specification

**Trạng thái:** PROPOSAL / P2.1–P2.2; không đồng nhất JSON hợp lệ với nội dung dạy tốt.

## 1. Learning objectives

- Dùng **Bloom's Taxonomy** để viết outcomes đo được (remember, understand, apply, analyze, evaluate, create), tránh chỉ dùng “hiểu rõ”.
- Gắn lesson với một hoặc nhiều outcomes và skill nodes; complexity phù hợp learner profile được user tự khai, không giả mastery thực tế.
- Từ cơ bản đến nâng cao theo prerequisite DAG; topological order dùng cho sequencing, không nhất thiết ép user tuân thủ tuyệt đối.
- Quiz bám sát teach content và objectives; tránh câu hỏi không có lời giải trong bài hoặc đáp án mơ hồ.
- Tutor khuyến khích làm từng bước và kiểm tra hiểu, không luôn cho đáp án trọn vẹn khi user đang trong quiz.

## 2. DAG validation

**Input:** `nodes[{skillId,label,bloomLevel?}]`, `edges[{prerequisiteSkillId,skillId}]`, `lessonSkillRefs`.

**Invariants (must test):**

1. Node IDs unique, label không rỗng.
2. Edge endpoints tồn tại, không self-loop, duplicate edge được reject/deduplicate minh bạch.
3. Directed graph **acyclic**; topological sort phải lấy đủ nodes, không tạo thứ tự giả nếu cycle.
4. Lesson references chỉ trỏ known skills, ít nhất một outcome tương ứng.
5. Không đặt hard rule mọi course phải có edges; beginner graph 1 node/0 edges là hợp lệ.

## 3. Evaluation dataset P2.2

**Tối thiểu 10 topics** đa dạng: 

| Topic example | Language / level | Risk to evaluate |
|---|---|---|
| Python cho người mới | vi / beginner | Progression & simple code |
| Cấu trúc dữ liệu: Hash Table | vi / intermediate | Definitions and collision handling |
| SQL căn bản | vi / beginner | Query correctness |
| Git & branching | vi / beginner | Procedural steps |
| Thống kê mô tả | vi / beginner | Numeric examples |
| Mạng máy tính TCP/IP | vi / intermediate | Layer misconceptions |
| English job interview | en / intermediate | Target language consistency |
| Linear algebra vectors | en / beginner | Math formatting & examples |
| Kỹ năng nghiên cứu học thuật | vi / intermediate | Avoid inventing references |
| Chủ đề mơ hồ “AI” | vi / unspecified | Clarify goal/unknown level |

Dùng fixtures không nhạy cảm, có answers/profile variants; split regression stable; lưu prompt version/model/schema version, dataset checksum.

## 4. Rubric per course/lesson (proposed 0–3 each)

| Dimension | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| Alignment | Không bám mục tiêu | Lệch nhiều | Chủ yếu phù hợp | Phù hợp rõ từng outcome |
| Progression | Sai prerequisite | Có gaps lớn | Logic chấp nhận | DAG & order hợp lý |
| Accuracy | Lỗi nghiêm trọng | Lỗi đáng kể | Lỗi nhỏ/cần review | Được reviewer kiểm chứng mẫu |
| Learner fit | Sai level rõ | Gượng ép | Khá phù hợp | Ví dụ/độ khó nhất quán |
| Quiz quality | Không có answerable quiz | Mơ hồ/sai key | Chấm được, còn vấn đề | Chấm được, bám nội dung |
| Clarity | Rối/thiếu | Khó theo dõi | Rõ cơ bản | Cấu trúc/ví dụ dễ hiểu |

**Mọi điểm rubric ngoài validation deterministic cần người review hoặc đánh giá có kiểm soát.** Nếu dùng LLM-as-judge: lưu model/prompt/version, sample human audit; không gọi là ground truth.

## 5. Acceptance metrics & gates

- **Deterministic gate:** 100% JSON valid theo schema, DAG no cycles, all links valid, lesson has teach+quiz, no leaked keys, no duplicate lesson title within scope, no invalid options.
- **Evaluative metrics:** rubric scores và rate of critical factual errors trên ít nhất 10 cases; kết quả `n`, failures, prompt/model version, token/latency/cost; không chỉ cherry-pick best output.
- **Cost:** theo job + stage + provider; ước lượng phí phải gắn bảng giá có timestamp/nguồn hoặc ghi unknown nếu không kiểm chứng.
- Ngưỡng trung bình rubric/maximum cost là **OPEN decision**, không tự chốt con số không dựa baseline.

## 6. Regression & reviewer workflow

1. Freeze dataset & expected deterministic validators.
2. Generate bằng mock/offline, fail nếu contract/graph invalid.
3. Với real provider đã được phép: run sampled topics, save redacted outputs/metrics có quyền; không đưa raw PII vào repo.
4. Review blind samples về pedagogy/accuracy; label lỗi: factual, coherence, difficulty, miskey, source hallucination, repetitiveness.
5. So sánh versions cùng dataset, báo improvements/regressions và cost tradeoff; không ra mắt nếu có critical safety/key leak/ownership failure.

## 7. Không làm

Không diễn giải nghiên cứu Bloom/Bastani/Kestin thành lời cam kết hiệu quả SopiSkill; không đổ lỗi chất lượng vào provider khi schema validator sai; không tự deploy adaptive deep learning chưa có dữ liệu.
