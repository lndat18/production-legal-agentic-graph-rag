# production-legal-agentic-graph-rag

- Agentic Graph RAG hỏi-đáp pháp luật Việt Nam; thiết kế sát production nhưng gọn; dự án cá nhân, public qua Cloudflare Tunnel.
- Python 3.14, quản lý bằng `uv`.

## Trạng thái dự án (2026-10-04): giai đoạn đầu

- Code hiện là baseline RAG kế thừa nguyên vẹn từ `production-legal-qa-rag`; lịch sử git làm lại từ đầu.
- Hướng phát triển: knowledge graph (Neo4j) + agent (LangGraph) để giải retrieval phức tạp hơn.
- Kiến trúc đích: `docs/architecture.png`, README mục "RAG vs. Agentic Graph RAG".
- Mọi thứ về graph/agent mới là kế hoạch, chưa triển khai.
- Mục "Baseline kế thừa" bên dưới là lịch sử hệ thống RAG gốc, không phải tiến độ của dự án này.

## Cấu trúc thư mục

- `src/production_legal_agentic_graph_rag/`: toàn bộ source import được, chia package theo nghiệp vụ.
- `tests/`: test, tên `test_<package>_<phần>.py`.
- `tools/`: CLI (Typer) chạy từng bước pipeline độc lập, vd. `tools/chunk_documents.py`.
- `data/`: raw → markdown → chunks → embeddings; `bm25/` cho sparse index.
- `models/`: model tải local, vd. vietnamese-reranker (chạy in-process, không host tách rời).
- `deploy/`: Docker compose production (chỉ phục vụ end-user), `deploy_spec.md`, `up.sh`/`down.sh`/`backup.sh`/`reset_cache.sh`; không phải code import được.
- `observability/`: Langfuse/Prometheus/Grafana compose, chạy cạnh production; tách khỏi `deploy/` (2026-09-29) vì không phục vụ end-user.
- `docs/`: tài liệu tổng quan (luồng một câu hỏi, kiến trúc, `baseline_history.md`).
- `.claude/`: cấu hình Claude Code: `agents/`, `skills/`, `settings.json`, `agent_problems.md` (quyết định + vấn đề còn mở của quy trình).

## Spec theo package

- Mỗi package có `<package>_spec.md` cạnh nó: nguồn sự thật cho thiết kế/quyết định; đọc trước khi sửa code trong package.
- Spec đã cô đọng (2026-09-30, rút gọn lần 2 2026-10-01; bản đầy đủ ở git history).
- **Giữ nguyên số mục** vì code/spec khác tham chiếu (`conversation_spec.md` mục 12.1, `observability_spec.md` mục 4.5, `evaluation_spec.md` mục 3.x/4.x…); đổi số mục làm hỏng tham chiếu.
- Dòng đầu mỗi spec: `Trạng thái: Draft | Approved (YYYY-MM-DD) | Implemented`.

## Package map (theo thứ tự pipeline)

- `formatting/`: `.docx` pháp luật → Markdown có cấu trúc, giữ vị trí pháp lý (Điều/Khoản/Điểm) ([spec](src/production_legal_agentic_graph_rag/formatting/formatting_spec.md)).
- `chunking/`: Markdown → chunk tự đủ nghĩa, sẵn sàng embedding ([spec](src/production_legal_agentic_graph_rag/chunking/chunking_spec.md)).
- `embedding/`: chunk → vector, giữ citation cho bước sinh câu trả lời ([spec](src/production_legal_agentic_graph_rag/embedding/embedding_spec.md)).
- `retrieval/`: câu hỏi → tập `RetrievedChunk` liên quan: HyDE, hybrid, RRF, MMR, rerank local GPU ([spec](src/production_legal_agentic_graph_rag/retrieval/retrieval_spec.md)).
- `generation/`: `RetrievedChunk` đã rerank → câu trả lời có citation, đã kiểm chứng ([spec](src/production_legal_agentic_graph_rag/generation/generation_spec.md)).
- `conversation/`: điều phối một lượt: condense → guardrail → cache → admission → retrieve → generate ([spec](src/production_legal_agentic_graph_rag/conversation/conversation_spec.md)).
- `cache/`: cache câu trả lời và kết quả retrieval bằng Redis, single-flight ([spec](src/production_legal_agentic_graph_rag/cache/cache_spec.md)).
- `api/`: FastAPI (OpenAI-compatible) + OpenWebUI + Redis + Postgres (chỉ cho OpenWebUI); spec tổng toàn hệ thống ([spec](src/production_legal_agentic_graph_rag/api/api_spec.md)).
- `observability/`: Langfuse trace một lượt hỏi + Prometheus `/metrics` cho `api` ([spec](src/production_legal_agentic_graph_rag/observability/observability_spec.md)).
- `evaluation/`: RAGAS; Phase 1 sinh golden testset, Phase 2 đã chạy đủ 157 mẫu (MMR tắt; kết quả ở README) ([spec](src/production_legal_agentic_graph_rag/evaluation/evaluation_spec.md)).

## Baseline kế thừa (từ production-legal-qa-rag)

- Hệ thống RAG gốc **Hoàn thành (2026-10-03)** và là nền của dự án này:
  - pipeline `formatting → chunking → embedding → retrieval → generation → conversation → cache → api` chạy end-to-end (API OpenAI-compatible + OpenWebUI + Redis)
  - deploy Docker + Cloudflare Tunnel; CD lên GHCR theo tag `vX.Y.Z`
  - observability (Langfuse/Prometheus/Grafana)
  - golden testset 157 câu và RAGAS Phase 2 (README mục "Baseline Evaluation", `data/eval/phase2/report.json`)
- Chính sách model/key LLM: `conversation_spec.md` mục 12.1.
- Chưa đo độ trễ/tải; chưa chọn cấu hình MMR.
- Tiến độ chi tiết, bài học vận hành (OpenWebUI PersistentConfig, `docker compose down`, cache wheel của uv…), ghi chú golden testset: [docs/baseline_history.md](docs/baseline_history.md).

## Nguyên tắc & bài học (chi tiết ở từng spec)

- **Đo bằng số trước khi đổi/tin; pilot nhỏ trước khi chạy dài.**
  - Mọi đổi prompt kèm vòng đo trên bộ ca; job tốn quota nhiều ngày phải pilot bằng CLI thật trước.
  - Điều tra nghi vấn bằng dữ liệu thật (fetch chunk thật) trước khi kết luận là bug; tìm đúng bên gây lỗi rồi chỉ sửa bên đó.
- **Code deterministic sở hữu cấu trúc và mọi kiểm tra xác định được; LLM chỉ làm phần ngôn ngữ/ngữ nghĩa.**
  - Đừng tin prompt tuyệt đối: sửa ở tầng code (chuẩn hoá citation `【n】`, guardrail setext).
  - Gate kiểm chứng **fail-closed** (Judge); guardrail đầu vào **fail-open** (availability).
  - Lỗi ngôn ngữ mơ hồ vá regex quá 3 vòng → chuyển sang LLM.
- **Hạn mức Groq là nút thắt thật.**
  - Rate limit theo `(tài khoản, model)`; TPD 200K là ràng buộc chính → cache bắt buộc.
  - 429 theo ngày: dừng ngay (circuit breaker); 429 theo phút: cooldown theo `retry-after`; 413 không retry được.
  - `reasoning_effort=low` cho bước nhẹ (medium tốn token gấp 3–5 lần).
- **Trạng thái dùng chung phải thread-safe từ đầu** (không "rủi ro chấp nhận được").
  - Checkpoint theo đơn vị nhỏ, ghi nguyên tử, **ghi dữ liệu trước, ghi trạng thái sau**.
  - "Đã xong" là file trạng thái riêng, không suy từ dữ liệu.
- **Log không chứa nội dung người dùng/thông điệp lỗi LLM** (không `exc_info`/`logger.exception`), không log key; bí mật chỉ ở `.env` (không commit, agent không đọc).
- **Quyết định thiết kế ≠ đã implement:** đọc lại code thật trước khi coi spec là xong; đổi model/prompt Judge phải bump `PROMPT_VERSION` (khoá cache).
- **Test phụ thuộc thư viện tuỳ chọn (ragas) bị CI bỏ qua:** chạy cục bộ trong venv `eval` (`--group eval --no-group production`, `~/.cache/eval-venv-run`) trước khi tin; CI xanh chưa đủ.

## Quy trình phát triển (`.claude/`)

- Vòng đời: spec → implement → test → review, bằng agent và skill riêng.
- Agent:
  - `architect` (Opus 5.5): brainstorm và chốt `*_spec.md` cùng người dùng (logic/workflow, lựa chọn công nghệ); đặt `Trạng thái: Draft`, khi người dùng xác nhận thì ghi `Approved (ngày)`.
  - `developer`: sở hữu `src/`; implement từ spec đã chốt; chỉ commit local, không push/mở PR.
  - `tester`: sở hữu `tests/`; viết unit/integration/data-schema test theo spec, chạy nhanh file test vừa sửa trước khi push; đảm nhiệm push + mở PR, tổng hợp feedback.
  - `reviewer`: review kiến trúc/logic/security/scalability đối chiếu spec + skill `coding-convention`; chạy local sau khi CI pass; PASS thì comment kết luận lên PR; không tự merge.
- Model: `architect` Opus 5.5; các agent còn lại Sonnet 5.5; tất cả `effort: medium`.
- Phân luồng lỗi theo người sở hữu: lỗi `src/` về `developer`; lỗi `tests/` và finding `test-coverage` về `tester`.
- Skill `develop-cycle` (`.claude/skills/develop-cycle/`): chạy vòng developer → tester → reviewer cho một spec; `argument-hint: <đường dẫn spec.md> <tên branch>`.
  - Điều kiện gọi: spec đã commit và `Trạng thái: Approved`; branch do người dùng tạo và đang checkout; worktree sạch.
  - Chỉ người dùng gọi được; Claude không tự gọi.
- Skill `coding-convention` (`.claude/skills/coding-convention/`): quy ước coding chuẩn production (cấu trúc thư mục, naming, format, docstring, pydantic/typer/ruff); `reviewer` đối chiếu theo skill này.
- `.claude/settings.json`:
  - allow: lệnh `git`/`gh`/đọc-file an toàn (status, log, diff, pr view/list/diff/checks, grep/rg/find/cat/ls…)
  - deny: `push --force`, `reset --hard`, `git clean`, `git branch -D`, `rm`, `find -delete/-exec`, đọc `.env`…
  - chỉ `tester` push/mở PR
- Danh sách vấn đề và quyết định của quy trình: `.claude/agent_problems.md`.

## Vận hành git/CI

- `main` được bảo vệ (bật 2026-10-04): bắt buộc PR, check `checks` xanh (`strict`), cấm force-push/xoá; admin bypass được.
- **Không dùng `[skip ci]`**: check treo pending, không merge được.
- CI chạy đủ khi diff **cả PR** đụng `src/`, `tests/`, `tools/`, `pyproject.toml`, `uv.lock`, `.github/workflows/` (spec `.md` dưới `src/` cũng tính).
- Merge squash: xoá branch cũ phải `git branch -D` (không phải `-d`); agent bị deny lệnh này, **người dùng tự chạy**.
- `git checkout main` khi còn sửa chưa commit ở file mà `main` có bản khác sẽ bị chặn → `git stash` trước.
- Quy ước git:
  - Tên branch `<loại>/<mô-tả-kebab-case>`, loại ∈ `feat`, `fix`, `refactor`, `docs`, `chore`, `test` (vd. `chore/agent-working`, `feat/kg-graph-retrieval`).
  - Branch ngắn hạn, tạo từ `main`, PR vào `main`, không lồng branch.
  - Commit message `loại(phạm-vi): mô tả` (conventional commits); commit do Claude tạo kết thúc bằng dòng `Co-Authored-By`.
  - Tag `vX.Y.Z` chỉ gắn trên `main` sau merge, ở mốc có thể phát hành; không gắn sau mỗi merge.
- **Sau khi sửa `CLAUDE.md` hoặc `.claude/` (agent, skill, settings), mở phiên Claude Code mới** trước khi gọi `develop-cycle`: subagent nhận bản `CLAUDE.md` đã nạp lúc bắt đầu phiên, không phải bản mới trên đĩa; định nghĩa agent và quyền cũng có thể chưa nạp lại.
- Việc không có spec (chore, docs, đổi tên, cấu hình): làm tay, không dùng `develop-cycle`; chỉ cần CI `checks` xanh rồi người dùng tự merge squash.
- Fix nhỏ trong `src/` (nhánh `fix/...`): làm tay, bắt buộc kèm regression test; áp dụng khi sửa khoảng ≤ 3 file và không đổi contract công khai. Vượt ngưỡng hoặc đổi hành vi thì phải có spec (`architect` → `develop-cycle`).
- Sau mỗi lần merge (người dùng tự làm):
  - `git checkout main && git pull`; `git branch -D <branch>`
  - đổi `Trạng thái:` của spec liên quan sang `Implemented`
  - cập nhật mục "Trạng thái dự án" nếu cần

## Lệnh dev

- `uv sync`: cài dependency (dev group gồm pytest, ruff, mypy).
- `uv run pytest`: chạy test; `-m "not slow"` bỏ test nạp model thật.
- `uv run ruff format .` và `uv run ruff check .`
- `uv run mypy src`: đúng lệnh CI (`mypy .` báo lỗi tên module ở `tools/`, có sẵn từ trước).
