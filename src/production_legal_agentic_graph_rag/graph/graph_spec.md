# Graph — Chunks → Knowledge Graph (Neo4j): Reference Spec

## 1. Mục đích

Dựng lại cấu trúc phân cấp (Văn bản → Phần → Chương → Mục → Điều → Khoản) và quan hệ
viện dẫn chéo giữa các Khoản thành một đồ thị trong Neo4j, để giải hai bài toán mà
retrieval vector cấp-Khoản (`retrieval_spec.md`, đã tuyên bố ngoài phạm vi ở mục "Agentic
decomposition cho câu nhiều Điều, cả Điều...") không giải được:

1. **Viện dẫn chéo trong một Khoản**: nội dung Khoản nhắc tới Điều/Khoản khác (cùng văn
   bản hoặc văn bản khác trong corpus) mà không có nó thì câu trả lời thiếu điều kiện áp
   dụng. Đo trên "Luật bảo hiểm xã hội" mẫu: 155/579 chunk (~27%) có viện dẫn kiểu này.
2. **Câu hỏi cấp Điều/Chương trở lên**: chunking chủ đích chunk theo Khoản
   (`chunking_spec.md` mục 1), nên một câu hỏi "Điều 10 quy định quyền gì" không có đơn vị
   chunk nào trả lời trọn vẹn — cần gộp đúng thứ tự mọi Khoản con của Điều đó.

Nguyên tắc cốt lõi:

> **Đồ thị chỉ để trả lời "còn thiếu gì" và "gộp lại thế nào" — không thay thế nội dung.**
> Neo4j sở hữu cấu trúc và quan hệ; Pinecone (đã có, xem `embedding_spec.md`) vẫn là
> nguồn duy nhất của nội dung (`content`). Không nhân đôi dữ liệu giữa hai hệ.

Package này (`graph/`) chỉ làm phần **ingest offline**: `data/chunks/**/*.json` → đồ thị
Neo4j. Cách Searching Agent gọi đồ thị lúc trả lời (Cypher template, MCP tool cụ thể)
thuộc `mcp_spec.md`/`agents_spec.md` sau này (CLAUDE.md mục 3), không phải spec này.

### Trong phạm vi

- Parse breadcrumb của mỗi `Chunk` thành đường dẫn phân cấp (Phần/Chương/Mục/Điều/Khoản),
  gộp các mảnh bị `is_split` thành một Khoản logic duy nhất.
- Trích viện dẫn chéo (`Điều`, `khoản ... Điều ...`) từ `content` của Khoản, phân biệt
  cùng văn bản/khác văn bản, resolve sang node đích khi văn bản đích có trong corpus.
- MERGE node + relationship vào Neo4j, idempotent theo cùng input.
- CLI Typer mỏng để chạy ingest thủ công/CI sau này.

### Ngoài phạm vi

- **Amend/Replace** (quan hệ sửa đổi/thay thế) — CLAUDE.md mục 3 liệt kê trong schema mục
  tiêu dài hạn, nhưng v1 này **chủ động không làm**: phần lớn câu chữ mang ý sửa
  đổi/thay thế nằm ở back matter ("được bổ sung theo...", "được bỏ theo..."), ngữ nghĩa
  khác hẳn "tham khảo thêm" của `REFERENCES` — trộn chung sẽ sai ý nghĩa quan hệ. Cần một
  vòng brainstorm riêng khi làm.
- **Front matter và back matter hoàn toàn không vào đồ thị** ở v1 (không tạo node, không
  quét viện dẫn) — xem lý do ở mục 5. Hệ quả trực tiếp: viện dẫn nằm trong chú thích sửa
  đổi cuối văn bản (chính là các câu Amend/Replace ở trên) không được `REFERENCES` bắt.
- **Node `Diem`**: Điểm không có identity độc lập trong chunking/Pinecone (chỉ là văn bản
  `a)`, `b)` bên trong `content`), nên v1 không tạo node riêng. Khi một viện dẫn trỏ tới
  điểm cụ thể ("điểm s khoản 1 Điều 62"), điểm đó chỉ là property trên edge `REFERENCES`
  (`target_diem: "s"`), không phải node.
- **Quan hệ thứ tự anh em `NEXT`** ("Chương 2 tiếp nối Chương 1") — không có use case cụ
  thể cho 2 bài toán ở mục 1, bỏ khỏi v1 (đã chốt cùng người dùng).
- Cách agent/MCP truy vấn đồ thị lúc serving, Cypher template cho từng loại câu hỏi.
- Thêm Neo4j vào `docker-compose`/CI (`deploy_spec.md`, `.github/workflows/ci.yml`) —
  thuộc mục việc riêng đã liệt kê trong `CLAUDE.md` mục 3.
- Resolve viện dẫn tới văn bản ngoài corpus (bỏ qua + log, xem mục 7).

## 2. Dữ liệu đầu vào & đầu ra

**Input**: `data/chunks/**/*.json` — cùng input với `embedding/` (`Chunk` Pydantic, xem
`chunking_spec.md` mục 2), đọc trực tiếp, không phụ thuộc `DocumentTree` nội bộ của
`chunking/parser.py` (đã bị bỏ sau khi chunking xong) và không re-run parser Markdown.
Lý do chọn hướng này thay vì mở lại phạm vi `chunking_spec.md`: khớp đúng luồng kiến trúc
đã chốt ("Chunks → Neo4j", `CLAUDE.md` mục 2), và breadcrumb đã đủ thông tin xác định vì
được sinh deterministic theo mục 4 `chunking_spec.md`.

**Output**: đồ thị Neo4j (node + relationship mô tả ở mục 5). Không ghi JSON checkpoint
trung gian ra `data/` — khác với `chunking`/`embedding`, ingest ở đây là một chặng
duy nhất (chunks → đồ thị), không có bước downstream nào khác cần đọc lại checkpoint.
`builder.py` (mục 8) vẫn tạo một `GraphDocument` Pydantic trong bộ nhớ trước khi ghi
Neo4j — đây là điểm test được mà không cần Neo4j thật (mục 9).

## 3. Bất biến không được phá vỡ

1. **Không nhân đôi nội dung.** Node không lưu `content`; chỉ lưu `chunk_ids` trỏ sang
   Pinecone. Lấy nội dung thật luôn qua `index.fetch(ids=...)` phía consumer (Searching
   Agent/MCP), không phải việc của package này.
2. **Một Khoản pháp lý = một node**, bất kể chunking có tách nó thành mấy `chunk_id` do
   vượt token budget (`is_split`). `Khoan.chunk_ids` giữ đúng thứ tự `split_index`.
3. **ID node ổn định, độc lập với tiêu đề.** ID tính từ toạ độ cấu trúc (văn bản + số
   Phần/Chương/Mục/Điều/Khoản), không tính từ tên Điều — sửa lỗi chính tả tên Điều không
   được làm đổi ID và mồ côi node cũ.
4. **Idempotent.** Chạy lại đúng input phải cho ra đúng đồ thị đó (`MERGE`, không
   `CREATE`) — cùng bất biến ID đã có ở `chunking_spec.md` mục 3.
5. **Không đoán viện dẫn.** Chỉ tạo `REFERENCES` khi cả Điều/Khoản đích và (nếu khác văn
   bản) văn bản đích đều xác định được trong corpus hiện có; mơ hồ thì bỏ qua + log, không
   suy luận bằng LLM (nhất quán triết lý deterministic của `chunking_spec.md`/`retrieval_spec.md`).
6. **Batch cô lập lỗi.** Một file/chunk lỗi không chặn phần còn lại của batch — cùng bất
   biến 7 ở `chunking_spec.md`.

## 4. Công cụ & công nghệ

- **Driver**: `neo4j` (official Python driver, Bolt protocol), dùng API `execute_query()`
  (tự quản lý session/transaction/retry, ít boilerplate hơn `session.write_transaction`
  kiểu cũ). Không dùng `langchain-neo4j`: giá trị chính của nó là `LLMGraphTransformer`
  (LLM tự suy luận entity/relationship từ text phi cấu trúc) và Cypher QA chain — không
  áp dụng được vì ingestion ở đây đã biết chính xác schema/luật trích xuất (mục 6-7), chỉ
  còn lại wrapper kết nối không rút gọn code đáng kể mà lại thêm dependency thừa tính
  năng. Cũng không dùng `neomodel` (OGM): xung đột quy ước Pydantic v2 sẵn có và không hợp
  kỹ thuật batch bên dưới. Thêm dependency qua `uv add neo4j`.
- **Kỹ thuật ghi: UNWIND batch, không loop `MERGE` từng node.** Theo đúng khuyến nghị
  chính thức của Neo4j cho bulk load: gom toàn bộ node cùng label (hoặc edge cùng type)
  từ `GraphDocument` thành một list tham số, chạy một câu `UNWIND $rows AS row MERGE (...)`
  duy nhất cho cả loạt, thay vì N round-trip cho N node. `neo4j_client.py` vì vậy chỉ cần
  một số nhỏ câu Cypher tĩnh (một cho mỗi label node, một cho `HAS_CHILD`, một cho
  `REFERENCES`), không phải một câu sinh động cho từng node/edge — ít code hơn, ít
  round-trip hơn, và tận dụng query cache tốt nhờ parameterized query.
- **Neo4j server**: Community Edition chạy local qua Docker (đúng triết lý hạ tầng cá
  nhân, `CLAUDE.md` mục 4) — việc thêm service vào `docker-compose` thuộc `deploy_spec.md`,
  ngoài phạm vi spec này; giả định trước khi chạy pipeline có Neo4j reachable qua
  `NEO4J_URI`.
- **Cấu hình**: thêm `GraphSettings` (`pydantic-settings`) vào `config.py` chung, đọc
  `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` từ `.env` — cùng pattern
  `EmbeddingSettings`/`RerankerSettings` đã có.
- **Không** import từ `retrieval/` (package đang tạm gitignore/untrack, `CLAUDE.md` mục 3
  "Lưu ý 2026-09-26") dù `retrieval/citation.py` có sẵn logic gần giống (parse breadcrumb,
  bảng văn bản trong corpus, regex nhận diện "Điều N"). `graph/` tự có bản của mình (mục
  6-7) để không phụ thuộc vào package đang ngoài phạm vi phát triển hiện tại. Đây là trùng
  lặp chấp nhận được ở quy mô nhỏ hiện tại; khi `retrieval/` quay lại phạm vi, cân nhắc
  tách phần dữ liệu thuần (bảng văn bản trong corpus) ra module dùng chung — không phải
  việc của spec này.

## 5. Schema đồ thị

### Node

| Label | Khoá nhận diện (`id`, hash SHA-256 từ) | Property khác |
| --- | --- | --- |
| `VanBan` | `source_document` (dùng trực tiếp, đã unique theo `chunking_spec.md`) | — |
| `Phan`, `Chuong`, `Muc` | `source_document` + nhãn cấp đó + mọi cấp cha (vd `"LUẬT BHXH\|Chuong:I"`) | `label: str` (nguyên văn sau "Chương "/"Mục "/"Phần ", giữ số La Mã nếu có, không ép `int`) |
| `Dieu` | `source_document` + toạ độ đủ tới Điều | `number: str`, `title: str` |
| `Khoan` | `source_document` + toạ độ đủ tới Khoản | `number: str \| None`, `chunk_ids: list[str]` (thứ tự `split_index`), `breadcrumb: str` (bản đầy đủ, để debug/log) |

Bỏ cấp không tồn tại trong toạ độ, giống quy tắc breadcrumb ở `chunking_spec.md` mục 4.
`title`/`label` **không** nằm trong khoá hash (bất biến 3, mục 3).

`number: str` (không `int`) cho cả `Dieu`/`Khoan`: corpus thật có Điều/Khoản mang hậu tố
chữ do sửa đổi luật chèn thêm mà không đánh số lại (`Điều 7a`/`48b` — Luật bảo hiểm y tế;
`Khoản 3a`/`5a`/`8a` — nhiều văn bản khác), ép `int` sẽ loại các Điều/Khoản này (và mọi
Khoản con) khỏi đồ thị — mất dữ liệu thật. Cùng lựa chọn và cùng lý do với
`chunking/models.py::KhoanNode.khoan_number: str | None` đã có sẵn.

**Khoản ngầm định cấp Điều**: một số Điều có nội dung nằm thẳng dưới heading Điều, không
tách Khoản riêng (`chunking_spec.md` mục 4, vd `"Điều 1. Phạm vi điều chỉnh"` không có
"Khoản 1." tường minh) — đo trên corpus mẫu, ~5% tổng số chunk. Vẫn tạo **một** node
`Khoan` cho trường hợp này (giữ đúng bất biến 2, mục 3: không bỏ nội dung hợp lệ), với
`number = None`; `id` hash dùng token cố định thay cho số Khoản để phân biệt với `id` của
chính `Dieu` cha. `HAS_CHILD` từ `Dieu` sang `Khoan` ngầm định này như bình thường.

### Relationship

| Type | Chiều | Property |
| --- | --- | --- |
| `HAS_CHILD` | cấp cha → cấp con liền kề (`VanBan`/`Phan`/`Chuong`/`Muc`/`Dieu` → cấp con), một loại duy nhất xuyên mọi cấp, bỏ cấp vắng mặt | — |
| `REFERENCES` | `Khoan` → `Dieu` hoặc `Khoan` → `Khoan` (khi viện dẫn có số Khoản) | `raw_text: str` (câu trích dẫn gốc, để debug), `target_diem: str \| None` |

### Ví dụ cụ thể (dữ liệu thật, "Luật bảo hiểm xã hội")

Khoản 7 Điều 2 có câu: *"...đã đủ tuổi nghỉ hưu theo quy định tại khoản 2 Điều 169 của Bộ
luật Lao động, trừ trường hợp... quy định tại khoản 7 Điều 33 của Luật này."*

```text
(VanBan "LUẬT BẢO HIỂM XÃ HỘI")-[:HAS_CHILD]->(Chuong "I")-[:HAS_CHILD]->
  (Dieu 2)-[:HAS_CHILD]->(Khoan 7)
      -[:REFERENCES {raw_text:"khoản 7 Điều 33 của Luật này"}]->(Khoan 33.7, cùng VanBan)
      -[:REFERENCES {raw_text:"khoản 2 Điều 169 của Bộ luật Lao động"}]->
        (Khoan 169.2, thuộc VanBan "BỘ LUẬT LAO ĐỘNG")
```

`Khoan 10.2` của Điều 10 (bị chunking tách `(phần 1/2)`/`(phần 2/2)` vì dài) là **một**
node với `chunk_ids=["cf1acc4a...", "ba1d7eda..."]` theo đúng thứ tự phần.

## 6. Parse breadcrumb và gộp `is_split`

`breadcrumb.py` (module mới, không tái dùng `retrieval/citation.py`, xem mục 4):

1. Bỏ chunk có breadcrumb thuộc front/back matter trước khi parse hierarchy — nhận diện
   bằng đúng 2 quy tắc đã định nghĩa ở `chunking_spec.md` mục 5: breadcrumb `== source_document`
   (front matter) hoặc chứa `"Chú thích sửa đổi (cuối văn bản)"` (back matter), cả hai có
   thể kèm hậu tố `(phần i/n)`. Log số lượng bỏ qua để đối chiếu tổng chunk.
2. Với chunk còn lại: cắt hậu tố `(phần i/n)` rồi hậu tố `- Điểm ...` (nếu Khoản có Điểm
   bị tách) để có **breadcrumb gốc** — dùng làm khoá gộp các mảnh `is_split`.
3. Định vị từng cấp trong breadcrumb gốc bằng regex nhận diện token cấp (`Phần `/`Chương
   `/`Mục `/`Điều `/`Khoản ` + số/nhãn ngay sau) theo đúng thứ tự xuất hiện trong
   `chunking_spec.md` mục 4 (bỏ cấp vắng mặt), **không** tách chuỗi thô theo `" - "` — dữ
   liệu thật có tên Điều tự chứa `" - "` (vd `"Điều 136. Trách nhiệm của Bộ Lao động -
   Thương binh và Xã hội"`, Luật bảo hiểm xã hội), tách literal sẽ vỡ tên Điều thành đoạn
   giả và làm rớt toàn bộ Khoản con của Điều đó ra khỏi đồ thị. `Điều {n}. {tên}` tách số
   và tên bằng dấu `.` đầu tiên sau số.
4. Gom mọi chunk có cùng breadcrumb gốc thành một `Khoan`, `chunk_ids` sắp theo
   `split_index` tăng dần (không tin thứ tự chunk trong file JSON).
5. Chunk lỗi (breadcrumb không khớp pattern nào ở bước 3) bị bỏ qua + log rõ
   `source_document`/`chunk_id`, không chặn batch (bất biến 6, mục 3).

## 7. Trích viện dẫn chéo

`documents.py`: bảng nhỏ `source_document → (document_key, aliases)` cho 6 văn bản mẫu
hiện có trong `data/raw` — tự viết mới cho `graph/`, không import `retrieval.citation.DOCUMENTS`
(mục 4). Thêm văn bản mới vào corpus phải cập nhật bảng này (nêu rõ ở mục 10).

`references.py`: quét `content` của mỗi `Khoan` (sau khi đã build hierarchy ở mục 6),
theo pattern:

```text
[(khoản|các khoản) (\d+[a-z]?)(, \d+[a-z]?)*( và \d+[a-z]?)? ]?Điều (\d+[a-z]?)[ của (<cụm từ văn bản>)]?
[điểm ...]?
```

Số Điều/Khoản có thể mang hậu tố chữ (`7a`, `48b`,...) cùng lý do mục 5 (Điều/Khoản sửa
đổi chèn thêm). **Liệt kê nhiều khoản trước một Điều** (`"các khoản 6, 7, 9 và 10 Điều
34"`) phải tạo **nhiều** `REFERENCES` edge từ cùng một `raw_text` gốc, mỗi edge một
`Khoan` đích — đây là core use case viện dẫn chéo (mục 1), không phải case ambiguous nên
không bị bất biến 5 (mục 3) chặn lại, chỉ đơn thuần cần pattern đủ rộng để bắt danh sách
số cách nhau bởi dấu phẩy/"và".

Với guard tránh false positive tương tự tinh thần `retrieval/citation.py` (không tái sử
dụng code, nhưng cùng nguyên tắc đã chứng minh đúng ở đó): biên từ (`\b`), không nhận khi
theo sau là đơn vị (tháng/năm/tuổi/%%...), không nhận "điều kiện"/"điều khoản"/"điều
hành". Resolve cụm văn bản bắt được (nếu có), sau khi chuẩn hoá NFC + lowercase + bỏ dấu:

- Khớp một trong các cụm tự-tham-chiếu (`"luật này"`, `"bộ luật này"`, `"nghị định
  này"`, `"thông tư này"`, `"pháp lệnh này"`, `"văn bản này"`) → **cùng văn bản**.
- Không có cụm "của ..." nào cả → mặc định **cùng văn bản** (trường hợp phổ biến nhất,
  155/579 chunk mẫu đều thuộc dạng này).
- Có cụm nhưng khớp alias trong `documents.py` → **khác văn bản**, target là `VanBan` đó.
- Có cụm nhưng không khớp alias nào → **không resolve được**, bỏ qua + log (bất biến 5).

Sau khi có `(khoan_list, dieu, document_target)` — `khoan_list` có thể rỗng (không nhắc
số Khoản), một số, hoặc nhiều số khi liệt kê: tìm node `Dieu` khớp trong đồ thị đã build
(cùng `VanBan` xác định ở trên). Với `khoan_list` rỗng, target là chính `Dieu`. Với mỗi số
trong `khoan_list`, nếu `Khoan` đó tồn tại dưới `Dieu` này thì tạo một `REFERENCES` edge
tới `Khoan` đó (cùng `raw_text` gốc cho mọi edge sinh từ một câu trích); số nào không tồn
tại thì bỏ qua riêng số đó + log, không chặn các số còn lại trong cùng danh sách. Không
tìm thấy Điều đích (target document có trong corpus nhưng không có Điều đó, ví dụ lỗi
đánh số nguồn) → bỏ qua + log toàn bộ câu trích, không tạo node giả (bất biến 5, mục 3
"Ngoài phạm vi").

## 8. Idempotency và cập nhật corpus

Corpus nhỏ (6 văn bản mẫu) → **full rebuild** là mặc định, cùng triết lý
`embedding_spec.md` mục 1: `MATCH (n) DETACH DELETE n` rồi ingest lại toàn bộ, thay vì
diff/incremental. Trong một lần rebuild, mọi `MERGE` (node theo `id`, relationship theo
cặp node + type) đảm bảo không tạo trùng nếu logic build có gọi lại (an toàn để retry).

## 9. Xử lý lỗi

| Sự cố | Hành vi |
| --- | --- |
| Breadcrumb không parse được (mục 6 bước 5) | Bỏ qua chunk, log `source_document`/`chunk_id`, tiếp tục batch |
| Viện dẫn mơ hồ/không resolve được (mục 7) | Bỏ qua, log `raw_text` + breadcrumb nguồn, không tạo edge |
| Mất kết nối Neo4j | Raise lỗi rõ ràng, dừng ingest — không âm thầm bỏ qua phần còn lại (khác với lỗi parse/reference ở trên, đây là lỗi hạ tầng phá tính đúng đắn toàn bộ, không phải lỗi cục bộ một chunk) |
| File chunk JSON không đọc được (hỏng/thiếu field) | Bỏ qua file đó, log, tiếp tục file khác — cùng bất biến batch cô lập lỗi của `chunking_spec.md` |

## 10. Thiết kế module

| Module | Trách nhiệm duy nhất |
| --- | --- |
| `models.py` | Pydantic: `GraphNode` (`VanBanNode`/`ChuongNode`/.../`KhoanNode`), `ReferenceEdge`, `GraphDocument`, `IngestResult`. |
| `documents.py` | Bảng văn bản trong corpus (`source_document → document_key/aliases`), chuẩn hoá text (NFC/lowercase/bỏ dấu). |
| `breadcrumb.py` | Parse breadcrumb → toạ độ phân cấp; lọc front/back matter; gộp `is_split` (mục 6). |
| `references.py` | Regex trích viện dẫn từ `content`, resolve target trong `GraphDocument` đã build (mục 7). |
| `builder.py` | Thuần function, không I/O: `list[Chunk] → GraphDocument` (gọi `breadcrumb.py` rồi `references.py`). Test được không cần Neo4j. |
| `neo4j_client.py` | `execute_query()` của driver chính thức; một câu Cypher `UNWIND ... MERGE` tĩnh cho mỗi label node và mỗi relationship type (mục 4), nhận `GraphDocument` gom thành list tham số; full rebuild (mục 8). |
| `pipeline.py` | Điều phối `builder` + `neo4j_client`, đọc toàn bộ `data/chunks/**/*.json`, trả `IngestResult` (số node/edge, số chunk bỏ qua). |

CLI Typer mỏng tại `tools/ingest_graph.py`, chỉ gọi `pipeline.run_ingest()`, không chứa
business logic — cùng pattern `tools/chunk_documents.py`.

```text
data/chunks/**/*.json
  → đọc toàn bộ Chunk
  → builder: lọc front/back matter, parse breadcrumb, gộp is_split → node cấp trên
  → builder: quét content mỗi Khoan → REFERENCES đã resolve
  → GraphDocument (Pydantic, trong bộ nhớ)
  → neo4j_client: full rebuild, MERGE toàn bộ node + relationship
  → IngestResult
```

## 11. Tiêu chí hoàn thành

- Mọi Khoản không thuộc front/back matter có đúng một node `Khoan`, `chunk_ids` đúng thứ
  tự kể cả khi bị `is_split`.
- Cây `HAS_CHILD` khớp đúng breadcrumb nguồn, bỏ đúng cấp vắng mặt, không tạo node thừa
  cho front/back matter.
- Viện dẫn cùng văn bản và khác văn bản (khi văn bản đích có trong corpus) đều tạo được
  `REFERENCES` đúng target; viện dẫn mơ hồ/ngoài corpus bị bỏ qua có log, không crash batch.
- Chạy lại `pipeline.run_ingest()` trên cùng input nhiều lần cho ra đồ thị giống hệt (số
  node/edge không đổi, không nhân đôi).
- `builder.py` test được đầy đủ bằng unit test thuần (input `list[Chunk]` mẫu, output
  `GraphDocument`), không cần Neo4j chạy thật; `neo4j_client.py` cần test tích hợp riêng
  (đánh dấu phù hợp để `pytest -m "not slow"` mặc định không yêu cầu Neo4j sống — quyết
  định marker cụ thể là việc của tester khi implement).
- Không có node/relationship nào chứa `content` — chỉ `chunk_ids`/breadcrumb/toạ độ.

## 12. Áp dụng cho corpus mới / mở rộng

Trước khi thêm văn bản mới vào corpus:

1. Cập nhật `documents.py` với `source_document` mới + alias hay dùng khi viện dẫn tới nó
   từ văn bản khác (thiếu → viện dẫn khác văn bản tới nó sẽ luôn bị bỏ qua vì "không khớp
   alias nào", mục 7).
2. Xác nhận breadcrumb văn bản mới vẫn khớp đúng pattern mục 6 (đặc biệt nếu văn bản có
   cấu trúc lạ: Phụ lục, Khoản gộp không có Điều bao ngoài — `chunking_spec.md` mục 4 đã
   có case này, breadcrumb parser ở đây phải xử lý nhất quán).
3. Nếu corpus đủ lớn để full rebuild (mục 8) không còn rẻ, cân nhắc incremental ingest —
   đó là thay đổi kiến trúc, chốt lại trước khi implement, không tự làm giữa chừng.
