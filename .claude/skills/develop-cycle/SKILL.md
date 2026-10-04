---
name: develop-cycle
description: Chạy vòng lặp developer → tester → reviewer cho một spec cụ thể
argument-hint: <đường dẫn spec.md> <tên branch>
disable-model-invocation: true
---
Bạn là orchestrator cho quy trình implement code từ spec. Input là `$ARGUMENTS`, gồm
chính xác hai phần: đường dẫn spec và tên branch. Người dùng đã tự tạo branch và commit
spec (đã chốt cùng agent `architect`) trước khi gọi command này; orchestrator không tạo
branch và không commit spec.

## Preflight

1. Tách và xác nhận spec path cùng branch name; cho phép bọc spec path trong dấu ngoặc
   kép nếu đường dẫn có khoảng trắng. Nếu thiếu, dư hoặc không thể tách an toàn hai tham
   số, dừng và yêu cầu người dùng gọi lại theo dạng `/develop-cycle <spec-path> <branch>`.
2. Xác nhận spec tồn tại, đã được commit, dòng `Trạng thái:` của spec bắt đầu bằng `Approved`, branch
   đã tồn tại và đang được checkout, và worktree không có thay đổi ngoài phạm vi task. Thiếu
   một điều kiện nào thì dừng và báo rõ blocker. Không tự đổi branch hoặc cất/loại bỏ thay
   đổi của người dùng khi worktree bẩn.
3. Xác nhận các subagent `developer`, `tester`, `reviewer` đều có sẵn. Xác nhận GitHub CLI
   đã đăng nhập trước khi giao phần việc cần remote GitHub cho tester/reviewer.
4. Lập state ledger gồm: spec path, branch, PR (ban đầu chưa có), `ci_feedback_count`,
   `design_feedback_count`, SHA mới nhất và feedback tích lũy. Nguồn sự thật của hai biến đếm
   là lịch sử PR, không phải hội thoại: đếm số comment mở đầu bằng `[ci-feedback]`
   (tester, `CHECKS_FAIL`) và `[design-feedback] REVISE` (reviewer) bằng
   `gh pr view <PR> --json comments --jq ...` (vd. đếm nhãn: `gh pr view <PR> --json comments --jq '[.comments[].body | select(startswith("[ci-feedback]"))] | length'`); không dùng
   `--comments` vì lỗi GraphQL ở `gh` 2.46. Chưa có PR thì cả hai bằng 0. Tính lại khi bắt đầu và sau
   mỗi lượt subagent, nên `/clear` hay chạy lại command không làm mất số đếm. Nếu số đếm
   trong hội thoại lớn hơn số đếm từ PR (vd. subagent quên post nhãn), lấy giá trị lớn hơn.
   Gọi các subagent tuần tự (foreground); không chạy song song các subagent có thể ghi vào
   cùng branch.

## Quy tắc điều phối

- Mỗi subagent (`developer`/`tester`/`reviewer`) KHÔNG có tool gọi subagent khác — mỗi lần
  được gọi chỉ làm đúng phần việc của lượt đó rồi trả handoff và dừng ngay, không tự chờ,
  không tự đọc phản hồi hay tự "chuyển sang" subagent kế tiếp. Toàn bộ trình tự gọi và relay
  feedback giữa các subagent là việc của orchestrator, không phải của agent con. Feedback
  được phân luồng theo người sở hữu lỗi: lỗi trong `src/` về `developer`; lỗi trong `tests/`
  và finding `test-coverage` về `tester`.
- Chỉ `tester` được push hoặc mở PR. KHÔNG agent nào (kể cả `reviewer`) được merge — merge
  vào `main` luôn do người dùng tự thực hiện thủ công sau khi `reviewer` PASS. Orchestrator
  tuyệt đối không tự `git push`, `gh pr create` hay `gh pr merge`.
- `developer` chỉ commit local trên branch đã chỉ định. Truyền cho agent này spec path,
  branch và toàn bộ feedback tích lũy của vòng trước.
- Feedback do CI fail (vòng A) làm tăng `ci_feedback_count` thêm 1; feedback do reviewer
  `REVISE` (vòng B) làm tăng `design_feedback_count` thêm 1 — hai biến đếm độc lập, không
  cộng dồn vào nhau. `test_migration_required` không tăng biến đếm nào (không phải lỗi, là
  bước bàn giao hợp lệ theo quy trình). Ngay khi MỘT trong hai biến đếm đạt 3, dừng toàn bộ
  quy trình, không gọi thêm subagent và báo người dùng cần can thiệp thủ công kèm mọi
  feedback/SHA/PR hiện có, nêu rõ biến đếm nào đã chạm ngưỡng.
- Nếu một subagent báo blocker, thiếu quyền, không thể xác minh trạng thái, hoặc developer
  báo **hard local gate** lỗi, dừng ngay. Không phỏng đoán, không bỏ qua gate và không gọi
  subagent kế tiếp. `test_migration_required` được developer khai báo đầy đủ theo role
  không phải hard-gate failure: tester phải cập nhật test theo spec rồi để GitHub Actions
  quyết định.
- Mỗi lần gọi subagent phải yêu cầu một handoff có cấu trúc: trạng thái, SHA/commit liên
  quan, PR nếu có, feedback theo định dạng đã quy định và hành động kế tiếp.
- Toàn bộ lệnh git/gh (đọc dữ liệu, push, mở PR, comment) cần cho quy trình này đã được cấp
  sẵn qua `.claude/settings.json`, TRỪ `gh pr merge` — lệnh này không được cấp quyền cho bất
  kỳ subagent nào, luôn cần người dùng tự chạy thủ công. Orchestrator và các subagent KHÔNG
  bao giờ dừng lại hỏi người dùng về quyền chạy các lệnh đã cấp sẵn còn lại. Chỉ dừng lại hỏi
  người dùng khi gặp quyết định thiết kế/implement mà spec chưa nêu rõ và ảnh hưởng trực tiếp
  tới chất lượng sản phẩm.

## Vòng lặp

Lặp lại các bước dưới đây cho đến khi reviewer `PASS`, hoặc bị dừng theo quy tắc trên.

### 1. Implement

Gọi subagent `developer` với:

- spec path và branch;
- feedback tích lũy của vòng trước (nếu có);
- yêu cầu đọc spec, implement đúng scope, chạy hard local gates mà developer agent quy
  định, báo kết quả `pytest` và khai báo `test_migration_required` nếu contract mới làm
  test cũ lỗi, rồi commit local.

Nếu developer báo hard local gate fail, dừng ngay và báo lỗi/log cho người dùng; không
gọi tester. Nếu `pytest` chỉ fail vì `test_migration_required` đã nêu rõ file/test, hành
vi cũ, hành vi mới và mục spec, lưu migration manifest cùng SHA rồi tiếp tục tester. Nếu
thành công, lưu SHA developer bàn giao.

### 2. Test, PR và CI — vòng A

Gọi subagent `tester` với spec path, branch, SHA/diff hiện tại, PR hiện tại (nếu có),
migration manifest (nếu có) và feedback cần được bảo vệ bằng test.

Tester phải viết/cập nhật test trong phạm vi `tests/`, push branch và chỉ mở PR nếu state
ledger chưa có PR. Tester theo dõi `checks` bằng GitHub CLI và trả về một trong ba trạng
thái:

- `CHECKS_FAIL` (kèm phân loại `source` / `test` / `unknown` của tester): tăng
  `ci_feedback_count`. Nếu đã là 3, dừng theo quy tắc điều phối. Nếu còn nhỏ hơn 3, thêm
  feedback CI vào ledger rồi: `test` → gọi lại tester (lặp bước 2, không qua developer);
  `source` → quay lại bước 1; `unknown` → quay lại bước 1 kèm cả hai giả thuyết của tester
  (developer kiểm tra source trước; nếu source đúng thì báo lại để lượt sau tới tester).
- `CHECKS_PASS`: lưu PR và SHA đã push, sau đó sang bước 3.
- `BLOCKED`: dừng ngay, nêu nguyên nhân và trạng thái PR/branch.

Không tự chạy lại hay đánh giá pytest, Ruff, mypy, ty hoặc pip-audit ở orchestrator;
`checks` là kết quả chính thức của vòng A.

### 3. Review local — vòng B

Gọi subagent `reviewer` với spec path, branch, PR và SHA đã vượt qua `checks`. Reviewer
phải tự xác nhận `checks` PASS, lấy PR diff chính thức, post feedback/kết luận lên PR và
trả về một trong ba trạng thái:

- `REVISE`: tăng `design_feedback_count`. Nếu biến đếm vẫn nhỏ hơn 3, đọc chính feedback
  reviewer trên PR, thêm vào ledger rồi phân luồng theo người sở hữu: finding về `src/` →
  bước 1 (developer) rồi bước 2; chỉ có finding `test-coverage` → thẳng bước 2 (tester), bỏ
  qua developer; có cả hai → developer trước, tester sau. Mọi lần lặp đều phải qua bước 2 để
  CI chạy lại trước review lần sau. Nếu đã là 3, dừng theo quy tắc điều phối.
- `PASS`: reviewer đã post comment PASS lên PR (có thể kèm các `nit` không chặn) và KHÔNG
  merge. Kết thúc vòng lặp — không gọi
  thêm subagent nào, chuyển sang phần "Kết quả cuối".
- `BLOCKED`: dừng ngay, nêu nguyên nhân và trạng thái PR/branch.

## Kết quả cuối

Khi kết thúc, báo ngắn gọn: spec, branch, PR, SHA cuối, `ci_feedback_count` và
`design_feedback_count`, trạng thái `checks`, kết luận reviewer. Nếu reviewer PASS: nêu rõ
PR đang chờ merge thủ công (nêu các `nit` nếu có để người dùng tự quyết), kèm lệnh gợi ý `gh pr merge <PR> --squash --delete-branch` để
người dùng tự chạy. Nếu dừng vì chạm ngưỡng một trong hai biến đếm hoặc vì `BLOCKED`, liệt
kê feedback còn lại theo đúng định dạng file/dòng/loại/mô tả để người dùng can thiệp.
