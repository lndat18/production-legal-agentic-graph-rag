# Lịch sử baseline kế thừa (production-legal-qa-rag)

Tài liệu lưu trữ: tiến độ và bài học của hệ thống RAG gốc tại 2026-10-03, chuyển nguyên văn
từ `CLAUDE.md` ngày 2026-10-04 để `CLAUDE.md` gọn hơn (file đó được nạp vào mọi phiên và
mọi subagent). Không phải tiến độ của dự án Agentic Graph RAG.

Trạng thái của hệ thống RAG gốc tại **2026-10-03: Hoàn thành (Done)**. Tóm tắt: phần lõi (pipeline → API → deploy end-user) đã xong và nghiệm
thu; CD đã xong (#76, phát hành `v0.1.0` ngày 2026-10-03); observe end-user, golden testset và Evaluation Phase 2 đã xong.

**Đã xong**
- Pipeline `formatting/` → `chunking/` → `embedding/` → `retrieval/` → `generation/` →
  `conversation/` → `cache/` → `api/`: có spec, có test, chatbot chạy end-to-end qua API
  OpenAI-compatible + OpenWebUI + Redis (Postgres chỉ còn phục vụ OpenWebUI).
- **Deploy production** (`deploy/`, chỉ phục vụ end-user): `deploy/up.sh` (tự dò GPU NVIDIA) / `deploy/down.sh`,
  public qua Cloudflare quick tunnel; `backup.sh` (pg_dump `openwebui`), `reset_cache.sh` (xoá cache Redis) nằm cạnh
  `up.sh`. Nghiệm thu thật ngày 2026-09-27 và **chạy lại sau #57–#62 ngày 2026-09-30** (đăng ký user thường,
  hỏi-đáp có citation, cache hoạt động) — phần observe đã nghiệm thu thủ công ngày 2026-10-03 (xem "Đã nghiệm thu thêm"). Lưu ý vận hành: `api` cần
  `mem_limit: 3g`; Groq giới hạn rate limit theo (tài khoản, model), không theo API key.
  Bài học 2026-09-30: (1) OpenWebUI lưu cấu hình vào DB (PersistentConfig) — giá trị chỉnh ở Admin Panel
  (vd. New Sign Ups) đè `ENABLE_SIGNUP` trong compose ở các lần khởi động sau; (2) `docker compose down` phải
  có `--env-file ../.env --profile '*'` (dùng `down.sh`), thiếu thì cloudflared sót và giữ network; (3) Dockerfile dùng
  `--mount=type=cache` cho cache wheel của uv để đổi dependency không tải lại torch; đừng `docker builder prune`;
  (4) Postgres chỉ 1 DB nên `POSTGRES_DB=openwebui`, đã bỏ `deploy/initdb/`.
- **Chính sách model/key LLM** (`conversation_spec.md` mục 12.1, PR #58): generation `gpt-oss-120b`
  xoay key 3 ⇄ 4; condense/HyDE/Judge `gpt-oss-20b`; guardrail `gpt-oss-safeguard-20b`;
  throttle theo bucket `(model, key)`.
- **Observability code** (PR #61): Langfuse trace + Prometheus/Grafana; `deploy/docker-compose.observe.yml`
  nối `api` production vào stack observe (`observability/`), `up.sh` tự ghép khi stack đang
  chạy. Prometheus chỉ scrape `api` production (`env=production`).
- **Gỡ `chatlog/`** (PR #62): Langfuse (self-host, riêng tư) là nơi duy nhất lưu nhật ký lượt hỏi-đáp
  (`observability_spec.md` mục 4.5, bảng ánh xạ trường `chat_turns` → trace). Đã bỏ `alembic/`,
  `sqlalchemy`/`asyncpg`, `tools/chatlog.py`, biến `CHATLOG_*`. Hệ quả: Langfuse không chạy thì mất
  nhật ký lượt đó — stack observe nên chạy cùng production. Dữ liệu `chat_turns` cũ trong Postgres
  production: người dùng tự drop. Dự án hiện tập trung vào phục vụ end-user + observe end-user.
- **Hạ tầng gọn:** đúng 1 cặp `.env`/`.env.example` ở repo root (3 block APP/DEPLOY/OBSERVABILITY,
  prefix `DEPLOY_`/`OBS_` cho biến trùng tên); `deploy/` chỉ chứa thứ phục vụ end-user, stack
  observe nằm ở `observability/` (root) (chạy: `./observability/up.sh` / `./observability/down.sh`; bật observe TRƯỚC rồi mới `./deploy/up.sh`).
- **Evaluation Phase 1** (sinh golden testset theo đơn vị, có checkpoint, chạy tiếp nhiều ngày,
  `tools/generate_testset.py`; PR #55, #60, #63, #64): dùng **9 key Groq** `GROQ_API_KEY_1..9` xoay vòng
  (`groq_round_robin.py`); 429 theo phút cooldown theo `retry-after`, đếm token thật theo key/đơn vị,
  `reasoning_effort=low` chỉ khi dựng KG, và **giữ phần đã sinh khi lỗi giữa đơn vị** (đơn vị `partial`
  chạy tiếp phần thiếu, không mất sample đã xong) — `evaluation_spec.md` mục 3.2, 3.3.
- **Evaluation Phase 2 — spec** (`evaluation_spec.md` mục 11, chốt lại **2026-10-01**): stage HyDE → embed → retrieve
  (MMR bật/tắt, tuần tự) → `context_recall` cả hai cấu hình → chọn MMR → generation → `faithfulness` + `answer_relevancy` →
  `context_precision`; 4 metric chuẩn RAGAS, file JSONL trung gian, resume theo `case_id`; generation chạy nguyên
  `GenerationPipeline` (phương án B); hàng đợi chung 9 key Groq + throttle chủ động theo `(model, key)`; testset cuối
  **157 câu (142 single + 15 multi-hop specific)** = mẫu `keep` của review luna (`data/eval/golden_testset_review.json`),
  không random, không duyệt tay; không pilot bắt buộc.

**Đã nghiệm thu thêm (2026-10-03)**
- **CD** (PR #76, `deploy_spec.md` mục 11): `release.yml` build + push image `api` lên GHCR theo tag `vX.Y.Z` (gate: commit thuộc `main` + check `checks` xanh;
  2 biến thể `-cpu`/`-cu126`, `latest` = cpu); `./deploy/up.sh --pull <vX.Y.Z>`. **Đã chạy thật 2026-10-03:** tag `v0.1.0` → gate + build xanh, GHCR đủ 3 tag, package public (kế thừa từ repo public).
  Không SSH tự động vào máy nhà; cập nhật vẫn thủ công.
- **Observe end-user**: stack observe + Langfuse trace + Prometheus/Grafana đã nghiệm thu thủ công trên production.
- **Evaluation Phase 2**: đã merge và chạy đủ 157 mẫu, MMR tắt; kết quả RAGAS trong README
  (`data/eval/phase2/report.json`). So sánh MMR bật/tắt chênh lệch nhỏ, chưa chọn cấu hình thắng cuộc; chưa đo độ trễ/tải.

**Golden testset (đã xong)**
- **Golden testset** (`data/eval/`): job `tools/generate_testset.py generate` **đã chạy hết, không còn process** (kiểm tra 2026-09-30 ~22:10):
  **49/50 đơn vị `done`, 1 `skipped`**, raw có **203 câu** (180 single-hop, 23 multi-hop specific,
  **0 multi-hop abstract**) — đã vượt 180; **chốt 2026-10-01: luna (Codex) review 203 mẫu, testset cuối = 157 mẫu `keep` (142 single + 15 multi-hop specific) trong `golden_testset.json` (đã sinh), không random, không duyệt tay**. Đơn vị `skipped` duy nhất:
  `Văn bản hợp nhất bộ luật lao động.md#5` (Chương IV + V, ~29K ký tự) — lỗi ở stage KG (bước `ThemesExtractor`,
  model trả JSON hỏng/rỗng → `OutputParserException`; lần trước là `OpenAITimeoutError`), 96 lượt tích luỹ qua 2 lần thử, 0 câu.
  `Quy định mức lương tối thiểu.md#1` đã chạy lại thành công (`--retry-skipped`, +9 câu). **Đã chốt bỏ** đơn vị này
  (203 > 180, BLLĐ còn nhiều đơn vị khác); nếu muốn thử nữa: `generate --retry-skipped --only "Văn bản hợp nhất bộ luật lao động.md#5"`
  (`generate` không tự chạy lại unit `skipped`). Hệ số token đo được 3,94 token/ký tự (thấp hơn ước tính 5,5).
  Cảnh báo `KG không có cụm cho loại abstract: bỏ N câu` vẫn xuất hiện đều.
  abstract = 0: **đã chốt chấp nhận** (`evaluation_spec.md` mục 4.6); `golden_testset.json` đã sinh; `finalize` đã sửa theo review trên nhánh Phase 2.

Hướng mở rộng sau khi Done (không chặn trạng thái Done; thứ tự đề xuất):

1. Lấy mẫu Q&A thật từ Langfuse để đánh giá bổ sung; chọn cấu hình MMR; đo độ trễ/tải.
2. Tách observability sang VM riêng: chưa chốt.
