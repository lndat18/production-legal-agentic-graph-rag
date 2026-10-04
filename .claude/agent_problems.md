# Quy trình agent: quyết định và vấn đề còn mở

- Phạm vi: `architect → /develop-cycle (developer → tester → reviewer) → merge thủ công`.
- Lịch sử chi tiết các vấn đề đã xử lý (mã A1–E2) nằm ở git history của branch `chore/agent-working`.

## Luồng hiện tại

- `architect`: chốt spec cùng người dùng; người dùng commit spec, tạo branch.
- `/develop-cycle <spec> <branch>` (người dùng gọi, phiên chính là orchestrator):
  - `developer`: code + commit local
  - `tester`: viết test, push, mở PR, chờ CI
  - `reviewer`: review local, comment `PASS`/`REVISE`/`BLOCKED` lên PR
- Người dùng: merge squash thủ công.
- Giới hạn: vòng A (CI lỗi) và vòng B (REVISE) mỗi vòng tối đa 3 lần, quá thì dừng.

## Quyết định đã chốt (2026-10-04)

- Quyền sở hữu: `tester` sở hữu `tests/`, `developer` sở hữu `src/`. Lỗi CI do test và finding `test-coverage` về `tester`; lỗi source về `developer`.
- Tester được chạy `uv run pytest -m "not slow" <file test vừa viết/sửa>` trước khi push; không chạy full suite, ruff, mypy. CI vẫn là kết quả chính thức.
- Người dùng tự tạo branch và commit spec trước `/develop-cycle`; spec cần `Trạng thái: Approved`.
- Việc không có spec (chore, docs, đổi tên, cấu hình): làm tay, chỉ cần CI xanh. Fix nhỏ trong `src/` (≤ 3 file, không đổi contract): nhánh `fix/`, làm tay, bắt buộc regression test.
- Tin prompt cho quy tắc "chỉ `tester` push"; không thêm hook.
- Giữ deny `git branch -D`; người dùng tự xóa branch sau merge.
- Đo golden testset bằng skill chạy tay, không đưa vào vòng lặp tự động.
- Neo4j: unit test dùng fake qua interface mỏng (vd. `GraphStore`); integration (marker `integration`) chạy Neo4j thật ở job CI riêng khi diff đụng package graph, ban đầu chưa bắt buộc. Chi tiết chốt trong spec graph; cần người chịu trách nhiệm chạy integration trước merge.
- Model: `architect` Opus 5.5; `developer`, `tester`, `reviewer` Sonnet 5.5; tất cả `effort: medium`.
- Số vòng đếm từ nhãn comment trên PR: `[ci-feedback]` (tester), `[design-feedback]` (reviewer).
- Repo: `main` bắt buộc PR + check `checks` xanh + strict, cấm force-push/xóa (admin bypass được); bật secret scanning, push protection, Dependabot security updates.
- Bỏ hẳn cấu hình Codex; `.claude/` là nguồn duy nhất.

## Còn mở

- **D1**: chưa có skill chạy golden testset (157 câu) để so baseline với graph retrieval; ràng buộc quota Groq.
- **D2**: chưa khai báo marker `integration` trong `pyproject.toml`, chưa có job CI Neo4j; làm khi viết spec graph (PR `chore` riêng, người dùng làm tay).
- **D3**: test-first vs test-after cho phần agent/graph khó đoán: chưa quyết.
- **D4**: trùng tên agent phát triển (`reviewer`, orchestrator `develop-cycle`) với agent sản phẩm (Orchestrator/Review Agent trong kiến trúc đích): cần quy ước thuật ngữ.
- **C2, C4**: chủ ý giữ (tin prompt cho push; người dùng tự khôi phục file bị xóa nhầm vì `git restore`/`git checkout --` bị deny).
- **C5, C6**: luật deny `.env` và `find -delete/-exec` chỉ ở mức best-effort (pattern Bash khớp theo chuỗi, có thể bị vòng qua); chưa thử từng luật bằng lệnh thật.
- **Chưa kiểm chứng**: `/develop-cycle` đầu-cuối; model `claude-opus-5-5`/`claude-sonnet-5-5` và `effort: medium` có hiệu lực khi chạy. Sau khi sửa `.claude/` hoặc `CLAUDE.md` phải mở phiên mới (subagent nhận context đã nạp lúc bắt đầu phiên).

## Lưu ý CI (ngoài phạm vi `.claude/`, chưa sửa)

- **E1**: bước `pip-audit` trong `ci.yml` có `continue-on-error: true` nên không làm `checks` đỏ; hoặc bỏ cờ này, hoặc coi pip-audit là cảnh báo (advisory).
- **E2**: bước "Xác định diff" của `ci.yml` thoát mã 128 khi SHA `before` của push không còn tồn tại (vd. sau force-push); sửa bằng `git cat-file -e "$BASE^{commit}"` rồi chạy full CI nếu thiếu. Cần PR riêng đụng `.github/workflows/`.
