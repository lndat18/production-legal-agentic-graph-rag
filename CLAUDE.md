# production-legal-agentic-graph-rag

Agentic Graph RAG hỏi-đáp pháp luật Việt Nam, thiết kế theo hướng sát production nhưng gọn
(dự án cá nhân, public qua Cloudflare Tunnel). Python 3.14, quản lý bằng `uv`.

**Trạng thái dự án (2026-10-04): giai đoạn đầu.** Code hiện là baseline RAG kế thừa nguyên
vẹn từ `production-legal-qa-rag` (lịch sử git làm lại từ đầu). Hướng phát triển: dùng
knowledge graph (Neo4j) và agent (LangGraph) để giải bài toán retrieval phức tạp hơn; kiến
trúc đích ở `docs/architecture.png`, README mục "RAG vs. Agentic Graph RAG". Mọi thứ về
graph/agent là kế hoạch, chưa được triển khai. Mục "Baseline kế thừa" bên dưới là lịch sử của hệ
thống RAG gốc, không phải tiến độ của dự án này.

## Cấu trúc thư mục

```
src/production_legal_agentic_graph_rag/   Toàn bộ source code import được (packages theo nghiệp vụ)
tests/                         Test, đặt tên test_<package>_<phần>.py
tools/                         CLI (Typer) chạy từng bước pipeline độc lập, vd. tools/chunk_documents.py
data/                          raw -> markdown -> chunks -> embeddings, bm25/ cho sparse index
models/                        Model tải local, vd. vietnamese-reranker (chạy in-process, không host tách rời)
deploy/                        Docker compose production (chỉ phục vụ end-user) + docs (deploy/deploy_spec.md), up.sh/down.sh/backup.sh/reset_cache.sh; không phải code import được
observability/                 Langfuse/Prometheus/Grafana compose (chạy cạnh production để quan sát end-user) — tách khỏi deploy/ (2026-09-29) vì không phục vụ end-user
docs/                          Tài liệu tổng quan hệ thống (luồng xử lý 1 câu hỏi, kiến trúc)
.claude/                       Cấu hình Claude Code cho project: agents/, skills/, settings.json, agent_problems.md (vấn đề + quyết định của quy trình)
```

Mỗi package trong `src/production_legal_agentic_graph_rag/` có một `<package>_spec.md` nằm ngay
cạnh nó, là nguồn sự thật cho thiết kế/quyết định của package đó — đọc trước khi sửa code
trong package tương ứng. Các spec đã **cô đọng 2026-09-30 và rút gọn lần 2 2026-10-01 (chỉ giữ phần bắt buộc)** (bản đầy đủ ở git history) và **giữ nguyên số
mục** vì code/spec khác tham chiếu (`conversation_spec.md` mục 12.1, `observability_spec.md` mục 4.5,
`evaluation_spec.md` mục 3.x/4.x…) — đổi số mục là làm hỏng các tham chiếu đó.

## Package map (theo thứ tự pipeline)

| Package           | Vai trò                                                                                                 | Spec                                                                                 |
| ----------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `formatting/`   | `.docx` pháp luật → Markdown có cấu trúc, giữ vị trí pháp lý (Điều/Khoản/Điểm)         | [formatting_spec.md](src/production_legal_agentic_graph_rag/formatting/formatting_spec.md)       |
| `chunking/`     | Markdown → chunk tự đủ nghĩa, sẵn sàng embedding                                                  | [chunking_spec.md](src/production_legal_agentic_graph_rag/chunking/chunking_spec.md)             |
| `embedding/`    | Chunk → vector, giữ citation cho bước sinh câu trả lời                                            | [embedding_spec.md](src/production_legal_agentic_graph_rag/embedding/embedding_spec.md)          |
| `retrieval/`    | Câu hỏi → tập`RetrievedChunk` liên quan (HyDE, hybrid, RRF, MMR, rerank local GPU)                | [retrieval_spec.md](src/production_legal_agentic_graph_rag/retrieval/retrieval_spec.md)          |
| `generation/`   | `RetrievedChunk` đã rerank → câu trả lời có citation, đã kiểm chứng                         | [generation_spec.md](src/production_legal_agentic_graph_rag/generation/generation_spec.md)       |
| `conversation/` | Điều phối 1 lượt hỏi đáp: condense → guardrail → cache → admission → retrieve → generate    | [conversation_spec.md](src/production_legal_agentic_graph_rag/conversation/conversation_spec.md) |
| `cache/`        | Cache câu trả lời & kết quả retrieval bằng Redis, single-flight                                    | [cache_spec.md](src/production_legal_agentic_graph_rag/cache/cache_spec.md)                      |
| `api/`          | FastAPI (OpenAI-compatible) + OpenWebUI + Redis + Postgres (chỉ cho OpenWebUI), spec tổng toàn hệ thống | [api_spec.md](src/production_legal_agentic_graph_rag/api/api_spec.md)                            |
| `observability/` | Langfuse trace 1 lượt hỏi + Prometheus `/metrics` cho `api`                                       | [observability_spec.md](src/production_legal_agentic_graph_rag/observability/observability_spec.md) |
| `evaluation/`   | Đánh giá bằng RAGAS: Phase 1 sinh golden testset (đã merge); Phase 2 đã merge và chạy đủ 157 mẫu (MMR tắt; kết quả ở README) | [evaluation_spec.md](src/production_legal_agentic_graph_rag/evaluation/evaluation_spec.md)       |

## Baseline kế thừa (từ production-legal-qa-rag)

Hệ thống RAG gốc đã **Hoàn thành (2026-10-03)** và là nền của dự án này: pipeline
`formatting → chunking → embedding → retrieval → generation → conversation → cache → api` chạy
end-to-end (API OpenAI-compatible + OpenWebUI + Redis), deploy Docker + Cloudflare Tunnel, CD
lên GHCR theo tag `vX.Y.Z`, observability (Langfuse/Prometheus/Grafana), golden testset 157 câu
và RAGAS Phase 2 (kết quả ở README mục "Baseline Evaluation", `data/eval/phase2/report.json`).
Chính sách model/key LLM: `conversation_spec.md` mục 12.1. Chưa đo độ trễ/tải; chưa chọn cấu
hình MMR. Tiến độ chi tiết, bài học vận hành (OpenWebUI PersistentConfig, `docker compose down`,
cache wheel của uv…) và ghi chú golden testset: [docs/baseline_history.md](docs/baseline_history.md).

## Nguyên tắc & bài học xương máu (đúc kết, chi tiết ở từng spec)

- **Đo bằng số trước khi đổi/tin, pilot nhỏ trước khi chạy dài.** Mọi đổi prompt kèm vòng đo trên bộ ca; job tốn quota nhiều ngày phải pilot bằng CLI thật trước. Điều tra nghi vấn bằng dữ liệu
  thật (fetch chunk thật) trước khi kết luận là bug; tìm đúng bên gây lỗi rồi chỉ sửa bên đó.
- **Code deterministic sở hữu cấu trúc và mọi kiểm tra xác định được; LLM chỉ làm phần ngôn ngữ/ngữ nghĩa.** Đừng tin prompt tuyệt đối — sửa ở tầng code (chuẩn hoá citation `【n】`, guardrail setext).
  Gate kiểm chứng **fail-closed** (Judge); guardrail đầu vào **fail-open** (availability). Lỗi ngôn ngữ mơ hồ vá regex quá 3 vòng → chuyển sang LLM.
- **Hạn mức Groq là nút thắt thật:** rate limit theo `(tài khoản, model)`, TPD 200K là ràng buộc chính → cache bắt buộc; 429 theo ngày phải dừng ngay (circuit breaker), 429 theo phút cooldown theo
  `retry-after`; `reasoning_effort=low` cho bước nhẹ (medium tốn token gấp 3–5 lần); 413 không retry được.
- **Trạng thái dùng chung phải thread-safe từ đầu** (không "rủi ro chấp nhận được"); checkpoint theo đơn vị nhỏ, ghi nguyên tử, **ghi dữ liệu trước, ghi trạng thái sau**; "đã xong" là file trạng thái riêng, không suy từ dữ liệu.
- **Log không chứa nội dung người dùng/thông điệp lỗi LLM** (không `exc_info`/`logger.exception`), không log key; bí mật chỉ ở `.env` (không commit, agent không đọc).
- **Quyết định thiết kế ≠ đã implement:** đọc lại code thật trước khi coi spec là xong; đổi model/prompt Judge phải bump `PROMPT_VERSION` (khoá cache).
- **Test phụ thuộc thư viện tuỳ chọn (ragas) bị CI bỏ qua** → chạy cục bộ trong venv `eval` (`--group eval --no-group production`, `~/.cache/eval-venv-run`) trước khi tin; CI xanh chưa đủ.

## Quy trình phát triển (`.claude/`)

Project có agent/skill riêng cho vòng đời spec → implement → test → review:

| Agent         | Vai trò                                                                                                                                                                                                            |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `architect` | (Opus 5.5) Brainstorm và chốt`*_spec.md` cùng người dùng trước khi implement (logic/workflow lẫn lựa chọn công nghệ); đặt `Trạng thái: Draft`, khi người dùng xác nhận thì ghi `Approved (ngày)` |
| `developer` | Sở hữu `src/`: implement code từ spec đã chốt; chỉ commit local, không push/mở PR                                                                                                                            |
| `tester`    | Sở hữu `tests/`: viết Unit/Integration/Data-schema test theo spec, chạy nhanh các file test vừa sửa trước khi push; đảm nhiệm push + mở PR để CI chạy, tổng hợp feedback                                     |
| `reviewer`  | Review kiến trúc/logic/security/scalability đối chiếu spec + skill`coding-convention`; chạy local sau khi CI pass, PASS thì comment kết luận lên PR — không tự merge, người dùng merge thủ công |

Các agent trừ `architect` dùng Sonnet 5.5; tất cả effort medium. Phân luồng lỗi theo người
sở hữu: lỗi `src/` về `developer`, lỗi `tests/` và finding `test-coverage` về `tester`.
Danh sách vấn đề và quyết định của quy trình: `.claude/agent_problems.md`.

Skill `develop-cycle` (`.claude/skills/develop-cycle/`) chạy trọn vòng lặp
developer → tester → reviewer cho một spec cụ thể (`argument-hint: <đường dẫn spec.md> <tên branch>`).
Điều kiện gọi: spec đã commit và có `Trạng thái: Approved`, branch do người dùng tạo và đang checkout, worktree sạch. Skill `coding-convention` (`.claude/skills/coding-convention/`) là quy ước
coding chuẩn production dùng chung (kiến trúc thư mục, naming, format, docstring, công cụ
pydantic/typer/ruff) — `reviewer` đối chiếu theo skill này.

`.claude/settings.json` allowlist các lệnh `git`/`gh`/đọc-file an toàn (status, log, diff,
pr view/list/diff/checks, grep/rg/find/cat/ls...) và deny các thao tác phá hoại
(`push --force`, `reset --hard`, `git clean`, `git branch -D`, `rm`, `find -delete/-exec`, đọc `.env`, ...). `develop-cycle` **chỉ người dùng gọi được**, Claude không tự gọi; chỉ `tester` push/mở PR.

**Lưu ý vận hành git/CI:** `main` bảo vệ (bật 2026-10-04): bắt buộc PR, check `checks` xanh (`strict`), cấm force-push/xoá; admin bypass được — **không dùng `[skip ci]`** (check treo pending, không merge được). CI chạy đủ khi diff **cả PR** đụng `src/`, `tests/`,
`tools/`, `pyproject.toml`, `uv.lock`, `.github/workflows/` (spec `.md` dưới `src/` cũng tính). Merge squash nên xoá branch cũ phải `git branch -D` (không phải `-d`) — agent bị deny lệnh này, **người dùng tự chạy**; `git checkout main` khi còn sửa chưa commit
ở file mà `main` có bản khác sẽ bị chặn → `git stash` trước.

**Quy ước git:** tên branch `<loại>/<mô-tả-kebab-case>` với loại ∈ `feat`, `fix`, `refactor`, `docs`, `chore`, `test`
(vd. `chore/agent-working`, `feat/kg-graph-retrieval`); mỗi branch ngắn hạn, tạo từ `main`, mở PR vào `main`, không lồng branch.
Commit message dạng `loại(phạm-vi): mô tả` (conventional commits), commit do Claude tạo kết thúc bằng dòng `Co-Authored-By`.
Tag `vX.Y.Z` chỉ gắn trên `main` sau merge, ở mốc phát hành.

**Sau khi sửa `CLAUDE.md` hoặc `.claude/` (agent, skill, settings), mở phiên Claude Code mới** trước khi gọi `develop-cycle`: dry-run cho thấy subagent nhận bản `CLAUDE.md` đã nạp lúc bắt đầu phiên chứ không phải bản mới trên đĩa; định nghĩa agent và quyền cũng có thể chưa được nạp lại.

**Làm việc không có spec** (chore, docs, đổi tên, cấu hình): làm tay, không dùng `develop-cycle`; chỉ cần CI `checks` xanh rồi người dùng tự merge squash.
**Fix nhỏ trong `src/`** (nhánh `fix/...`): làm tay, không dùng `develop-cycle`, bắt buộc kèm regression test; áp dụng khi sửa khoảng ≤ 3 file và không đổi contract công khai. Vượt ngưỡng đó hoặc đổi hành vi thì phải có spec (qua `architect` → `develop-cycle`).
**Sau mỗi lần merge** (người dùng tự làm): `git checkout main && git pull`, `git branch -D <branch>`, đổi `Trạng thái:` của spec liên quan sang `Implemented`, cập nhật mục "Trạng thái dự án" nếu cần. Chỉ gắn tag `vX.Y.Z` ở mốc có thể phát hành, không gắn sau mỗi merge.

## Lệnh dev

```bash
uv sync                    # cài dependency (dev group gồm pytest, ruff, mypy)
uv run pytest              # chạy test; -m "not slow" để bỏ test nạp model thật
uv run ruff format .
uv run ruff check .
uv run mypy src            # đúng lệnh CI (`mypy .` báo lỗi tên module ở tools/, có sẵn từ trước)
```
