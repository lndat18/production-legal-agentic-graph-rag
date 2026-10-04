# Vấn đề của quy trình agent (`.claude/`)

Ghi lại các điểm mâu thuẫn, chưa rõ và cần cải tiến trong quy trình
`architect → /develop-cycle (developer → tester → reviewer) → merge thủ công`.
Mỗi mục có mã để tham chiếu khi chốt; trạng thái mặc định **open**. Chưa sửa gì trong
`agents/`, `skills/` hay `settings.json` — file này chỉ là danh sách vấn đề để brainstorm.

Quy trình hiện tại (đọc từ `agents/*.md`, `skills/develop-cycle/SKILL.md`):

```
architect (chốt spec cùng người dùng)
   └─▶ /develop-cycle <spec> <branch>   (người dùng gọi, orchestrator là phiên chính)
         developer: code + commit local
           → tester: viết test, push, mở PR, chờ CI
             → reviewer: review local, comment PASS/REVISE lên PR
               → người dùng: merge thủ công
   Vòng A (CI lỗi) và vòng B (REVISE): mỗi vòng tối đa 3 lần, quá thì dừng.
```

## A. Mâu thuẫn trong pipeline

**A1. Lỗi CI luôn quay về `developer`, dù lỗi có thể nằm ở test do `tester` viết.**
`CHECKS_FAIL` → skill quay lại bước 1 (developer). Nhưng `tester` không được chạy pytest
local nên viết test "mù", lần CI đầu rất dễ fail vì chính test. `developer` thì chỉ sửa
source và không có nhiệm vụ sửa `tests/` (trừ `test_migration_required`). Hệ quả: feedback
`test-fail` tới developer mà nó không có gì để sửa, và vẫn tiêu một lượt của
`ci_feedback_count`. Cần quy tắc phân loại: lỗi do test thì quay về tester, lỗi do source
mới quay về developer.

**A2. Finding `test-coverage` của reviewer cũng bị route về `developer`.**
Reviewer được flag `test-coverage`, nhưng `REVISE` → bước 1 (developer) → mới tới tester.
Finding loại này cần tester bổ sung test, developer không có gì để đổi trong `src/`.
Cùng gốc với A1: routing theo vòng (A/B) chứ không theo người sở hữu lỗi.

**A3. Ai commit file spec? Preflight bắt worktree sạch.**
`architect` bị cấm `git commit`; `developer` chỉ commit file "thuộc phạm vi thay đổi";
`develop-cycle` yêu cầu worktree không có thay đổi ngoài phạm vi. Spec vừa được architect
ghi xong sẽ là file chưa commit ngay trước khi chạy `/develop-cycle`. Chưa nói rõ: người
dùng tự commit spec, hay spec được xem là thuộc phạm vi và developer commit chung.

**A4. Spec "không cần nêu test" nhưng tester/reviewer lại suy test từ spec.**
`coding-convention` ghi "Không cần đề cập đến việc viết tests trong spec — đã có agent
CI/CD riêng". Trong khi tester "bảo vệ spec bằng test" và reviewer flag `test-coverage` khi
"spec đã nêu case quan trọng" mà thiếu test. Nếu spec cố ý không nói về test thì các case
quan trọng (đặc biệt lỗi, biên) phải nằm trong spec dưới dạng hành vi. Ngoài ra "agent
CI/CD riêng" đã lỗi thời: job `reviewer-agent` đã bị bỏ khỏi `ci.yml`.

**A5. Từ vựng trạng thái handoff không khớp giữa skill và agent.**
Skill dùng `CHECKS_PASS` / `CHECKS_FAIL` / `BLOCKED` cho tester và `PASS` / `REVISE` /
`BLOCKED` cho reviewer. `tester.md` chỉ nhắc `CHECKS_PASS`; `reviewer.md` không có
`BLOCKED`. Orchestrator phải tự suy ra trạng thái từ văn bản tự do.

## B. Chưa rõ

**B1. Ai tạo và checkout branch?** Skill: "branch tồn tại hoặc có thể được tạo an toàn từ
`main`", nhưng orchestrator không được làm việc khác ngoài điều phối, và developer chỉ
"commit local trên branch được chỉ định". Chưa nói ai chạy `git checkout -b`.

**B2. Developer báo hard local gate fail thì dừng toàn bộ.** Không rõ developer được tự
sửa và chạy lại trong cùng lượt hay không. Cách đọc hiện tại: chỉ báo cáo khi gate đã xanh,
fail nghĩa là kẹt thật và người dùng phải can thiệp.

**B3. Công việc không có spec (chore, docs, đổi tên, README).** Pipeline giả định có spec
và code. Không có "làn" cho thay đổi như PR #1; hiện phải làm tay, bỏ qua cả
`develop-cycle`. Cần chốt: làm tay là chấp nhận được, hay cần một quy ước nhẹ (vd. không cần
reviewer, chỉ cần CI xanh).

**B4. Ledger chỉ sống trong hội thoại.** `ci_feedback_count` / `design_feedback_count` mất
khi `/clear` hoặc hết context. Sau khi dừng ở ngưỡng 3 và người dùng can thiệp, chưa nói
đếm lại từ 0 hay tiếp tục.

**B5. Sau merge không ai chịu trách nhiệm.** Xóa branch, tag/release, cập nhật "Tiến độ"
trong `CLAUDE.md` đều ngoài pipeline.

## C. Cấu hình `settings.json` và quy tắc

**C1. `git branch -D` bị deny, nhưng `CLAUDE.md` bắt buộc dùng nó** để xóa branch đã
squash-merge (`-d` không dùng được). Hai nơi mâu thuẫn; đã gây lỗi khi thao tác thực tế.

**C2. "Chỉ `tester` được push/mở PR" chỉ nằm trong prompt.** `settings.json` allow
`git push *` và `gh pr create *` cho mọi agent và cả phiên chính. Không có chốt chặn kỹ
thuật. Chọn một: tin prompt, hoặc thêm hook / quyền theo agent.

**C3. Câu "không được cấp quyền `gh pr merge`" thực ra chỉ là "không nằm trong allowlist".**
Lệnh sẽ hiện hộp xác nhận chứ không bị cấm; chỉ `gh pr merge --admin*` bị deny. Cách nói
trong `reviewer.md` mạnh hơn thực tế.

**C4. `git restore *` và `git checkout -- *` bị deny** nên mọi agent không khôi phục được
file bị xóa nhầm; người dùng phải tự chạy. Có chủ ý (an toàn) nhưng cần ghi nhận.

## D. Thiếu so với nhu cầu của project mới

**D1. Không có bước đo chất lượng thật.** `CLAUDE.md` đặt nguyên tắc "đo bằng số trước khi
đổi", nhưng cả 4 agent chỉ kiểm tra lint, type, test đơn vị. Chưa có bước chạy golden
testset 157 câu để so baseline với phiên bản graph retrieval. Ràng buộc: quota Groq. Ứng
viên: skill đánh giá chạy tay, không nhất thiết là agent mới.

**D2. CI chưa có Neo4j.** Test cho package graph hoặc phải dùng fake, hoặc `ci.yml` cần
service container (sửa workflow nằm ngoài quyền developer/tester). Cần chốt trong spec của
package graph.

**D3. Test-first vs test-after.** Hiện tester viết test sau khi developer xong. Với phần
agent/graph có hành vi khó đoán, viết test từ spec trước có thể làm spec rõ hơn và bắt lỗi
sớm hơn, nhưng đổi thứ tự pipeline.

**D4. Trùng tên giữa agent phát triển và agent sản phẩm.** Kiến trúc đích có
"Orchestrator Agent" / "Review Agent" chạy lúc người dùng hỏi, còn `.claude/` có
`reviewer` và orchestrator `develop-cycle` phục vụ lập trình. Nên có quy ước tên hoặc thuật
ngữ tách bạch trong tài liệu.

**D5. Model.** Cả 4 agent dùng `model: sonnet`. `architect` và `reviewer` là hai vai trò
cần suy luận sâu nhất; có thể cân nhắc model mạnh hơn cho hai vai trò này.

## Thứ tự đề xuất khi chốt

1. Sửa mâu thuẫn rẻ và rõ: **C1**, **A4** (phần lỗi thời), **A5**.
2. Chốt luật routing theo người sở hữu lỗi: **A1**, **A2**.
3. Chốt quy ước vận hành: **A3**, **B1**, **B3**.
4. Quyết định hướng cho project mới: **D1**, **D2**, **D3**.
