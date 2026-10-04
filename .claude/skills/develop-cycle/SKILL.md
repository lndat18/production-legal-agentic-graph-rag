---
name: develop-cycle
description: Chạy vòng lặp developer → tester → reviewer cho một spec cụ thể
argument-hint: <đường dẫn spec.md> <tên branch>
disable-model-invocation: true
---
# Develop cycle (orchestrator)

- Vai trò: orchestrator của quy trình implement code từ spec; input `$ARGUMENTS` gồm đúng hai phần: đường dẫn spec và tên branch.
- Người dùng đã tự tạo branch và commit spec (đã chốt với `architect`) trước khi gọi; orchestrator không tạo branch, không commit spec.

## Preflight

- Tách và xác nhận spec path + branch (cho phép bọc spec path trong dấu ngoặc kép nếu có khoảng trắng). Thiếu, dư hoặc không tách an toàn: dừng, yêu cầu gọi lại `/develop-cycle <spec-path> <branch>`.
- Xác nhận đủ điều kiện, thiếu một điều kiện nào thì dừng và báo blocker:
  - spec tồn tại, đã commit, dòng `Trạng thái:` bắt đầu bằng `Approved`
  - branch đã tồn tại và đang checkout
  - worktree không có thay đổi ngoài phạm vi task (không tự đổi branch, không cất/loại bỏ thay đổi của người dùng)
- Xác nhận subagent `developer`, `tester`, `reviewer` có sẵn và GitHub CLI đã đăng nhập.
- Lập state ledger: spec path, branch, PR (ban đầu chưa có), `ci_feedback_count`, `design_feedback_count`, SHA mới nhất, feedback tích lũy.
  - Nguồn sự thật của hai biến đếm là lịch sử PR: đếm comment mở đầu bằng `[ci-feedback]` (tester, `CHECKS_FAIL`) và `[design-feedback] REVISE` (reviewer).
  - Lệnh đếm: `gh pr view <PR> --json comments --jq '[.comments[].body | select(startswith("[ci-feedback]"))] | length'`. Không dùng `--comments` (lỗi GraphQL ở `gh` 2.46).
  - Chưa có PR: cả hai bằng 0. Tính lại khi bắt đầu và sau mỗi lượt subagent, nên `/clear` hay chạy lại không mất số đếm.
  - Số đếm trong hội thoại lớn hơn số từ PR (subagent quên post nhãn): lấy giá trị lớn hơn.
- Gọi subagent tuần tự (foreground); không chạy song song các subagent có thể ghi cùng branch.

## Quy tắc điều phối

- Subagent không có tool gọi subagent khác: mỗi lượt chỉ làm phần việc của mình rồi trả handoff và dừng. Gọi tuần tự và relay feedback là việc của orchestrator.
- Phân luồng feedback theo người sở hữu lỗi: lỗi `src/` về `developer`; lỗi `tests/` và finding `test-coverage` về `tester`.
- Chỉ `tester` push/mở PR. Không agent nào merge; merge do người dùng thủ công sau khi reviewer PASS. Orchestrator không tự `git push`, `gh pr create`, `gh pr merge`.
- `developer` chỉ commit local trên branch đã chỉ định; truyền cho nó spec path, branch, toàn bộ feedback tích lũy của vòng trước.
- Hai biến đếm độc lập, không cộng dồn:
  - CI fail (vòng A): `ci_feedback_count` +1
  - reviewer `REVISE` (vòng B): `design_feedback_count` +1
  - `test_migration_required` không tăng biến đếm nào (bước bàn giao hợp lệ, không phải lỗi)
  - Một trong hai biến đếm đạt 3: dừng toàn bộ, không gọi thêm subagent, báo người dùng can thiệp kèm mọi feedback/SHA/PR và nêu biến đếm nào chạm ngưỡng.
- Dừng ngay khi: subagent báo blocker/thiếu quyền/không xác minh được trạng thái, hoặc developer báo hard local gate lỗi. Không phỏng đoán, không bỏ qua gate, không gọi subagent kế tiếp. `test_migration_required` khai báo đầy đủ không phải hard-gate failure.
- Mỗi lần gọi subagent yêu cầu handoff có cấu trúc: trạng thái, SHA/commit liên quan, PR (nếu có), feedback theo định dạng quy định, hành động kế tiếp.
- Quyền: mọi lệnh git/gh cần cho quy trình (đọc, push, mở PR, comment) đã cấp sẵn trong `.claude/settings.json`, TRỪ `gh pr merge` (chỉ người dùng tự chạy). Không hỏi người dùng về quyền các lệnh đã cấp; chỉ hỏi khi gặp quyết định thiết kế mà spec chưa nêu và ảnh hưởng trực tiếp chất lượng.

## Vòng lặp

- Lặp các bước 1–3 đến khi reviewer `PASS` hoặc bị dừng theo quy tắc trên.

### 1. Implement

- Gọi `developer` với: spec path + branch; feedback tích lũy của vòng trước (nếu có); yêu cầu đọc spec, implement đúng scope, chạy hard local gates, báo kết quả `pytest`, khai báo `test_migration_required` nếu contract mới làm test cũ lỗi, rồi commit local.
- Developer báo hard local gate fail: dừng, báo lỗi/log cho người dùng; không gọi tester.
- `pytest` chỉ fail vì `test_migration_required` (đã nêu file/test, hành vi cũ, hành vi mới, mục spec): lưu migration manifest cùng SHA, tiếp tục tester.
- Thành công: lưu SHA developer bàn giao.

### 2. Test, PR và CI (vòng A)

- Gọi `tester` với: spec path, branch, SHA/diff hiện tại, PR hiện tại (nếu có), migration manifest (nếu có), feedback cần bảo vệ bằng test.
- Tester viết/cập nhật test trong `tests/`, push branch, chỉ mở PR nếu ledger chưa có PR, theo dõi `checks`, trả một trong ba trạng thái:
  - `CHECKS_FAIL` (kèm phân loại `source` | `test` | `unknown`): `ci_feedback_count` +1.
    - Đã là 3: dừng theo quy tắc điều phối.
    - Còn dưới 3: thêm feedback CI vào ledger rồi:
      - `test` → gọi lại tester (lặp bước 2, không qua developer)
      - `source` → quay lại bước 1
      - `unknown` → quay lại bước 1 kèm cả hai giả thuyết của tester (developer kiểm tra source trước; source đúng thì báo lại để lượt sau tới tester)
  - `CHECKS_PASS`: lưu PR và SHA đã push, sang bước 3.
  - `BLOCKED`: dừng ngay, nêu nguyên nhân và trạng thái PR/branch.
- Orchestrator không tự chạy lại hay đánh giá pytest/Ruff/mypy/ty/pip-audit; `checks` là kết quả chính thức của vòng A.

### 3. Review local (vòng B)

- Gọi `reviewer` với: spec path, branch, PR, SHA đã qua `checks`. Reviewer tự xác nhận `checks` PASS, lấy PR diff, post feedback/kết luận lên PR, trả một trong ba trạng thái:
  - `REVISE`: `design_feedback_count` +1.
    - Đã là 3: dừng theo quy tắc điều phối.
    - Còn dưới 3: đọc feedback reviewer trên PR, thêm vào ledger, phân luồng theo người sở hữu:
      - finding về `src/` → bước 1 (developer) rồi bước 2
      - chỉ có `test-coverage` → thẳng bước 2 (tester), bỏ qua developer
      - có cả hai → developer trước, tester sau
    - Mọi lần lặp đều qua bước 2 để CI chạy lại trước review kế tiếp.
  - `PASS`: reviewer đã post comment PASS (có thể kèm `nit` không chặn), không merge. Kết thúc vòng lặp, không gọi thêm subagent, sang "Kết quả cuối".
  - `BLOCKED`: dừng ngay, nêu nguyên nhân và trạng thái PR/branch.

## Kết quả cuối

- Báo ngắn gọn: spec, branch, PR, SHA cuối, `ci_feedback_count`, `design_feedback_count`, trạng thái `checks`, kết luận reviewer.
- Reviewer PASS: nêu PR đang chờ merge thủ công, nêu các `nit` (nếu có) để người dùng tự quyết, kèm lệnh gợi ý `gh pr merge <PR> --squash --delete-branch`.
- Dừng vì chạm ngưỡng hoặc `BLOCKED`: liệt kê feedback còn lại theo định dạng `file | dòng | loại | mô tả` để người dùng can thiệp.
