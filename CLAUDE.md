# CLAUDE.md

Hướng dẫn cho Claude Code (và mọi agent khác đọc file này) khi làm việc trong repo này.
Đọc file này trước khi brainstorm spec, implement, test hay review bất kỳ phần nào.

## 1. Dự án là gì

Chatbot hỏi–đáp pháp luật Việt Nam, hướng **production** nhưng chạy trên **hạ tầng cá
nhân** (laptop, không cloud/K8s — xem mục 4). Đây là bản nâng cấp kiến trúc của
[`production-legal-qa-rag`](../production-legal-qa-rag) (repo cũ, đã clone làm nền cho
repo này): từ RAG một lượt (retrieve → generate) lên **agentic + graph RAG** — multi-agent
orchestration (LangGraph) và Knowledge Graph (Neo4j) bên cạnh vector search (Pinecone) đã
có sẵn.

**Quan hệ 2 repo (đã chốt 2026-09-25): fork độc lập.** Code kế thừa
(`chunking/`, `embedding/`, `retrieval/`, `conversation/`, `cache/`, `formatting/`,
`generation/`, `chatlog/`, `api/`, `deploy/`) là điểm khởi đầu/tham khảo khi cần đối
chiếu hành vi cũ — **không backport 2 chiều**, sửa gì trong repo này chỉ ảnh hưởng repo
này.

## 2. Kiến trúc mục tiêu

Nguồn chân lý: `docs/images/architecture.png`. Đọc ảnh này
trước khi viết bất kỳ spec nào đụng tới phần MỚI dưới đây.

**Offline flow (ingestion, batch)** — DOCX → chunk, rồi rẽ 2 nhánh song song:

| Nhánh                  | Công nghệ                                                               | Trạng thái              |
| ----------------------- | ------------------------------------------------------------------------- | ------------------------- |
| Vector (dense + sparse) | Embedding qua HuggingFace → Pinecone (dense) + BM25 → Pinecone (sparse) | Đã có (`embedding/`) |
| Knowledge Graph         | Chunks → Neo4j (graph database)                                          | **Mới, chưa có** |

**Online flow (serving, real-time)** — Người dùng → Cloudflare Tunnel → OpenWebUI →
FastAPI → **LangGraph multi-agent**:

| Agent              | Vai trò                                                                                                                                                             | LLM            | Trạng thái                                                              |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- | ------------------------------------------------------------------------- |
| Orchestrator Agent | Điều phối, quyết định bước tiếp theo                                                                                                                        | ChatGPT / Groq | Mới — thay cho`conversation/orchestrator.py` (đơn-agent hiện tại) |
| Searching Agent    | Retrieval: hybrid search (keyword + similarity) → RRF → MMR → rerank cross-encoder (đã có),**cộng** graph retrieval qua **MCP** nối Neo4j (mới) | ChatGPT / Groq | Retrieval vector đã có, graph + MCP chưa có                          |
| Review Agent       | Duyệt/kiểm tra câu trả lời trước khi trả về                                                                                                                 | ChatGPT / Groq | Mới — nâng cấp từ`generation/guardrail.py` + `output_check.py`   |

Serving layer bên dưới (FastAPI, PostgreSQL cho chatlog/OpenWebUI, Redis cho
cache/quota/rate-limit, Docker) **giữ nguyên** từ repo cũ — xem `api/api_spec.md`,
`deploy/deploy_spec.md`.

**Quan sát & đánh giá (mới, làm ở phase sau):**

- Tracing/tracking: Langfuse, Prometheus, Grafana; CI/CD: GitHub Actions (đã có bản cơ
  bản, xem mục 3)
- Evaluation: ragas, DeepEval

## 3. Trạng thái hiện tại (2026-09-26) & việc cần làm

**Đã có** (kế thừa từ `production-legal-qa-rag`, đủ spec + code + test, xem
`src/production_legal_agentic_graph_rag/*/*_spec.md`):

- Offline: chunking, embedding (dense HF→Pinecone), sparse index (BM25→Pinecone)
- Online: retrieval (hybrid + RRF + MMR + rerank), conversation orchestrator đơn-agent
  (guardrail/condense/admission), cache (single-flight, quota), generation
  (guardrail/judge/output_check), chatlog, api (FastAPI + OpenWebUI + Redis + Postgres),
  deploy (docker compose + Cloudflare Tunnel)
- CI cơ bản: `.github/workflows/ci.yml` chạy `pytest -m "not slow"`, `ruff check`,
  `ruff format --check`, `mypy src`, `pip-audit` (chỉ khi diff đụng `src/`/`tests/`/`tools/`)
- `data/` có 6 văn bản luật mẫu đã qua pipeline offline cũ (raw → markdown → chunks →
  embeddings), dùng để phát triển/test phần mới
- `docs/online_flow.md` mô tả luồng đơn-agent **hiện tại** — sẽ cần vẽ lại khi
  `agents_spec.md` thành hình

**Lưu ý (2026-09-26):** `api/`, `cache/`, `chatlog/`, `conversation/`, `generation/`,
`retrieval/` dưới `src/production_legal_agentic_graph_rag/` đang bị gitignore + untrack
tạm thời (xem `.gitignore`) trong lúc trọng tâm phát triển là `chunking/`, `embedding/`,
`formatting/` và `graph/` mới. Code các package này vẫn còn nguyên trên đĩa ở working
tree hiện tại (chạy/tham khảo được bình thường) nhưng **không còn nằm trong git** —
clone mới của repo này từ commit hiện tại sẽ không có các thư mục đó cho tới khi được
add lại có chủ đích.

**Chưa có — trọng tâm phát triển tiếp theo, chưa có spec nào:**

- [X] **Đổi tên package** `production_legal_qa_rag` → `production_legal_agentic_graph_rag`
  — đã chốt 2026-09-25, **đã thực hiện trong code** 2026-09-26 (branch `rename-package`,
  chờ merge vào `main`): `pyproject.toml` và `src/production_legal_agentic_graph_rag/`
  cùng toàn bộ import liên quan đã dùng tên mới.
- [ ] Schema Knowledge Graph pháp luật trong Neo4j (Văn bản–Điều–Khoản–Điểm, quan hệ
  tham chiếu/sửa đổi/thay thế...) + pipeline ingest từ chunks → graph
- [ ] MCP layer: expose retrieval (vector + graph) thành MCP server/tools cho các agent
  LangGraph gọi
- [ ] LangGraph multi-agent: Orchestrator / Searching / Review agent thay thế
  `conversation/orchestrator.py`
- [ ] Observability: Langfuse tracing, Prometheus metrics, Grafana dashboard
- [ ] Evaluation: ragas + DeepEval, tích hợp vào CI
- [ ] Rà lại `.github/workflows/ci.yml` khi thêm service mới (Neo4j) cần test tích hợp

Mỗi hạng mục trên đi qua quy trình spec-driven ở mục 5 — **architect chốt `*_spec.md`
trước khi implement**, không nhảy thẳng vào code.

## 4. Triết lý "sát production nhất có thể, hạ tầng cá nhân"

- **Hạ tầng:** 1 laptop cá nhân, docker compose, Cloudflare Tunnel — không cloud/K8s/managed
  service (kế thừa triết lý `deploy/deploy_spec.md`). Giới hạn RAM/VRAM là ràng buộc thật,
  không lý thuyết — cân nhắc kỹ khi quyết định thành phần nào chạy local (reranker, Neo4j)
  vs. gọi API ngoài (Groq, ChatGPT, Pinecone).
- **Nhưng kỷ luật production giữ nghiêm:** mọi thay đổi đi qua spec → test → CI → review
  (mục 5); observability (Langfuse/Prometheus/Grafana) và evaluation (ragas/DeepEval)
  không phải "nice-to-have" bỏ qua khi thiếu thời gian — là tiêu chí hoàn thành của spec
  liên quan, ghi rõ trong `*_spec.md` như các spec hiện có đã làm (mục "Không làm" phải
  nêu rõ, không im lặng bỏ qua).
- **Multi-agent + Graph RAG là đánh đổi latency/cost lấy chất lượng** (nhiều bước suy luận,
  review trước khi trả lời), **không phải để scale số người dùng đồng thời**. Quota/rate
  limit/global budget kiểu repo cũ (`conversation_spec.md` mục 8) vẫn cần thiết — quan
  trọng hơn trước, vì multi-agent tốn token/lượt nhiều hơn kiến trúc 1-shot cũ.

## 5. Quy trình phát triển (đã thiết lập sẵn — áp dụng cho cả phần mới)

Spec-driven, 4 vai trò tuần tự: **architect → developer → tester → reviewer**.

- **architect**: brainstorm & chốt `<package>_spec.md` cùng người dùng, đặt cạnh package
  nó mô tả (vd. `src/production_legal_agentic_graph_rag/graph/graph_spec.md`, sau khi đổi
  tên ở mục 3) — không gom vào thư mục `specs/` riêng. Không tự implement code nguồn.
- **developer**: implement đúng spec, chỉ commit local (không push/mở PR).
- **tester**: viết/cập nhật test, push branch, mở PR, theo dõi CI (`checks`).
- **reviewer**: review diff so với spec + coding-convention; `PASS` thì comment kết luận
  lên PR và dừng lại — không tự merge, merge vào `main` do người dùng tự thực hiện thủ
  công.

Chạy cả vòng bằng lệnh `/develop-cycle <spec-path> <branch>` (xem
`.claude/skills/develop-cycle/SKILL.md`). Định nghĩa 4 vai trò này chỉ sống ở `.claude/`
(Claude Code) — repo chỉ dùng công cụ này, không cần bản sao cho CLI khác.

Quyền chạy lệnh git/gh cho quy trình này đã cấp sẵn qua `.claude/settings.json` — xem
trước khi hỏi lại người dùng về quyền chạy lệnh. Lưu ý: `gh pr merge` KHÔNG nằm trong
danh sách cấp sẵn cho bất kỳ subagent nào — luôn cần người dùng tự chạy thủ công.

## 6. Coding convention

Xem đầy đủ tại skill `coding-convention` (`.claude/skills/coding-convention/SKILL.md`). Tóm tắt:

- Code import được nằm trong `src/production_legal_agentic_graph_rag/` (đã đổi tên, xem
  mục 3); mỗi domain nghiệp vụ một package riêng (`chunking/`, `retrieval/`, `graph/`,
  `agents/`, `mcp/`,...), không gộp logic khác domain vào chung 1 thư mục.
- `snake_case` module/hàm/biến, `PascalCase` class, `UPPER_SNAKE_CASE` hằng số, prefix
  `_` cho nội bộ module. Tên mô tả rõ hành vi, tránh viết tắt tối nghĩa.
- **Pydantic v2** `BaseModel` cho mọi cấu trúc dữ liệu trao đổi giữa package (không
  `dict` thô/`dataclass` trần). **Typer** cho mọi CLI trong `tools/` (không `argparse`).
- Toolchain: `uv` (dependency), `ruff` (lint + format), `mypy` (type check), `pip-audit`
  (security).
- Docstring PEP 257 cho mọi module/class/public function. Comment giải thích **tại sao**,
  không giải thích **cái gì**.

## 7. Lệnh hay dùng

```bash
uv sync --all-groups          # cài dependency (kể cả dev)
uv run pytest -m "not slow"   # test nhanh, khớp CI
uv run pytest                 # test đầy đủ kể cả test nạp model thật
uv run ruff check .           # lint
uv run ruff format .          # format
uv run mypy src               # type check
uvx pip-audit                 # audit dependency
```

## 8. Cấu trúc thư mục

```
src/production_legal_agentic_graph_rag/
  chunking/       embedding/      formatting/  config.py    __init__.py
  # api/, cache/, chatlog/, conversation/, generation/, retrieval/
  # — kế thừa từ repo cũ, gitignore + untrack tạm thời, xem mục 3
  # <package mới>/graph/, agents/, mcp/  — chưa tồn tại, mục 3
tests/            # 1 test module tương ứng mỗi package trên
tools/            # CLI Typer, script vận hành (chunk/embed/retrieval/generation/...)
data/             # raw (docx) → markdown → chunks → embeddings, dữ liệu mẫu
deploy/           # Dockerfile, docker-compose, deploy_spec.md
docs/             # architecture.png, online_flow.md
.claude/          # agent + workflow config (mục 5)
```

## 9. Ghi chú miền pháp luật Việt Nam

- Đơn vị cấu trúc văn bản pháp luật: **Điều → Khoản → Điểm** — đã là cơ sở cho chunking
  (`chunking_spec.md`); dùng lại đúng cấp bậc này khi thiết kế node/relationship cho
  `graph_spec.md` (mục 3) thay vì tạo lược đồ mới không khớp.
- `data/raw` hiện có 6 văn bản mẫu (BHXH, BHYT, thuế TNCN, lao động, lương tối thiểu) —
  dùng để phát triển và test pipeline graph/agent mới trước khi mở rộng corpus.
