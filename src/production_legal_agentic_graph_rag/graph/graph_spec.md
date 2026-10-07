# Graph — Ingest văn bản pháp luật vào Neo4j: Reference Spec

Trạng thái: Approved (2026-10-05)

- Spec liên quan: [chunking_spec.md](../chunking/chunking_spec.md), [embedding_spec.md](../embedding/embedding_spec.md), [retrieval_spec.md](../retrieval/retrieval_spec.md).
- Số mục cố định sau khi `Approved`. Các điểm chưa chốt gom ở mục 12.

## 1. Mục đích & phạm vi

- Dựng knowledge graph trong Neo4j từ `data/markdown/**/*.md` để:
  - **Mục tiêu 1, câu hỏi phạm vi rộng hơn Khoản:** lấy toàn bộ phần con của một đơn vị cấu trúc (Điều/Mục/Chương/Phần) và đi từ một Khoản lên cha/anh em, bằng truy vấn xác định. Mức Khoản đã có trong Pinecone;
  - **Mục tiêu 2, viện dẫn chéo:** hiểu và truy vấn được viện dẫn giữa các Điều/Khoản/Điểm trong cùng một văn bản.
- Nguyên tắc phân vai: graph trả lời "bên trong X có gì" (cấu trúc, tra theo định danh); Pinecone trả lời "nội dung nào liên quan" (ngữ nghĩa). Chọn đường vào nào thuộc spec retrieval/agent.
- Làm: parse hierarchy, tạo node/cạnh cấu trúc, trích và phân giải viện dẫn nội bộ, ghi Neo4j idempotent, kiểm tra sau ingest, báo cáo.
- Không làm:
  - viện dẫn đa văn bản (viện dẫn ra văn bản khác chỉ đếm vào báo cáo, không tạo cạnh);
  - embedding hay vector index trong Neo4j (vector search vẫn ở Pinecone);
  - entity/khái niệm pháp lý, câu hỏi theo khái niệm rải nhiều Chương/văn bản (dạng G, mục 1.1), LLM dựng cấu trúc;
  - **tóm tắt LLM cấp Điều/Mục/Chương**, gom nhóm chủ đề: tiêu đề của nhà làm luật đã là phân nhóm; text cấp trên chỉ gộp khi truy vấn;
  - bộ đánh giá câu hỏi phạm vi rộng (golden testset 157 câu không đo được mục tiêu 1; để spec retrieval/agent);
  - retrieval và agent (spec riêng, sau spec này);
  - job CI cho Neo4j (người dùng làm tay trong PR `chore`).

### 1.1 Dạng câu hỏi graph phục vụ (mục tiêu 1)

- Đo trên corpus: golden testset gần như không có câu rộng hơn Khoản (chỉ ~2–3/157, vd. #24 "Chương VII quy định gì"; top-5 Pinecone chỉ phủ 3/12 Điều của Chương VII). Điều 4 Luật TNCN có 22 Khoản = 22 chunk (~733 token); top-5 chỉ trả tối đa 5/22.
- Kích thước: Chương trung vị ~3–4K token, lớn nhất (BHXH Chương V) ~25K token; ngân sách throttle 8K TPM mỗi bucket (`conversation_spec.md` mục 12.1) → không gộp nguyên văn cả Chương; phải đọc mục lục trước rồi mở chọn lọc.
- Dạng phục vụ (A–F):
  - A. Tổng quan một đơn vị: "Chương VII quy định gì" → mục lục (con theo `order`, tiêu đề, `char_count`), sau đó mở toàn văn trong ngân sách;
  - B. Một chế độ trải nhiều Điều: từ Khoản trúng Pinecone nâng lên Điều, Mục/Chương, lấy Điều/Khoản anh em;
  - C. Điều kèm điều viện dẫn để câu trả lời đầy đủ: trả thẻ viện dẫn, mở đích khi cần (mục 4, 7). Vd. Luật BHXH Điều 66 Khoản 4 ("2,25% mức bình quân tiền lương … quy định tại Điều 72") cần Điều 72 mới biết cách tính;
  - D. Toàn văn một Điều: "Điều 4 Luật TNCN có những gì" → gộp Khoản/Điểm theo `order`;
  - E. Liệt kê/đếm cấu trúc: đếm Mục/Điều/Khoản/Điểm bằng Cypher xác định;
  - F. So sánh: lấy song song hai cây con (việc so sánh nội dung là của LLM).
- Dạng G (theo khái niệm, rải nhiều Chương/văn bản): ngoài phạm vi.
- Hai đường vào graph, cùng một cây phân cấp: (1) định danh tường minh ("Điều 4 luật TNCN") → tra `(Document.short_name, label)`; (2) chỉ có ngữ nghĩa → Pinecone → `chunk_id` → `Clause` → cha/anh em.

## 2. Số liệu đo trên corpus (căn cứ thiết kế)

- Đo bằng regex trên `data/chunks` (6 văn bản, 2026-10-04); viện dẫn dạng `[điểm][khoản] Điều …`:

| Văn bản | Chunk | Điều | "Điều này" | "… này" (nội bộ) | Nêu văn bản khác (ngoại) | "Điều N" trần |
|---|---|---|---|---|---|---|
| Luật BHXH | 579 | 141 | 143 | 200 | 37 | 35 |
| Luật BHYT | 328 | 57 | 69 | 98 | 171 | 35 (7 không có Điều đích) |
| Luật TNCN | 121 | 29 | 30 | 15 | 4 | 2 |
| Bộ luật Lao động (hợp nhất) | 704 | 220 | 78 | 102 | 23 | 17 |
| NĐ điều kiện lao động | 436 | 115 | 60 | 76 | 141 | 118 (29 không có Điều đích) |
| Mức lương tối thiểu | 60 | 5 | 0 | 0 | 0 | 1 |

- Lưu ý: số "Điều N trần" ở NĐ trong bảng đếm theo chunk, nên bị thổi phồng do câu dẫn lặp ở các chunk con của Khoản dài (vd. Điều 89 lặp 6 lần). Theo câu duy nhất, sau khi loại câu nêu tên văn bản khác và câu có "này", chỉ còn **32 câu**, tập trung ở 4 Khoản (Điều 1 K1–K10, Điều 8 K3, Điều 41 K1, Điều 89 K1). Graph lấy viện dẫn từ `Clause.text` (một lần mỗi Khoản), không từ chunk, nên không bị trùng.
- Kết luận:
  - "Điều này", "khoản X Điều này", "… của Luật/Nghị định/Bộ luật này" phân giải được bằng quy tắc xác định.
  - "Điều N" trần trong văn bản hướng dẫn (NĐ/TT) **mơ hồ thật**: vd. NĐ Điều 1 Khoản 4 ghi "theo khoản 4 Điều 63" là Điều 63 của Bộ luật Lao động, dù NĐ cũng có Điều 63 riêng (ca làm việc). Chỉ kiểm tra "đích tồn tại" sẽ nối nhầm.
  - Viện dẫn ngoại phổ biến (Luật BHYT chứa nội dung sửa đổi, NĐ dẫn Bộ luật) → phải loại, không nối.
  - Có "từ Điều X đến Điều Y" (7 lần) và viện dẫn mức Điểm (~63 lần).

## 3. Bất biến không được phá vỡ

- Graph chỉ chứa cạnh `REFERS_TO` đã phân giải được tới node có thật trong cùng văn bản; không cạnh treo, không cạnh sang văn bản khác.
- **Ưu tiên precision hơn recall:** nối nhầm gây hại hơn bỏ sót; ca không chắc thì không tạo cạnh.
- `id` node và `chunk_id` ổn định, deterministic; `chunk_id` trong graph phải khớp `chunk_id` của chunking (mục 5).
- Ingest idempotent: chạy lại cùng input cho cùng graph.
- Mỗi văn bản ghi trong một transaction; lỗi văn bản này không để graph dở dang hay chặn văn bản khác.
- Cypher hoàn toàn tham số hoá; không ghép chuỗi từ nội dung văn bản.
- Log không chứa nội dung văn bản/thông điệp lỗi LLM; không log key.

## 4. Schema graph

- Node: `Document`, `Part` (Phần), `Chapter` (Chương), `Section` (Mục), `Article` (Điều), `Clause` (Khoản), `Point` (Điểm).
- Cạnh cấu trúc: `Document-[:HAS_PART|HAS_CHAPTER|HAS_SECTION|HAS_ARTICLE]->…`, `Article-[:HAS_CLAUSE]->Clause`, `Clause-[:HAS_POINT]->Point`.
  - Cạnh trỏ tới cấp con trực tiếp, không bắc cầu; cấp văn bản không có thì bỏ qua (Điều gắn thẳng Chương nếu không có Mục).
- Thuộc tính:
  - mọi node: `id`, `order` (thứ tự anh em);
  - `Document`: `name` (= `source_document`), `short_name` (lấy từ tên file markdown, vd. `Luật thuế thu nhập cá nhân`; để khớp tên văn bản trong câu hỏi), `kind` (`goc` | `huong_dan`, mục 6), `front_text`, `back_text`;
  - `Part`/`Chapter`/`Section`: `number` kiểu **int** (số La Mã đổi sang int), `label` giữ bản gốc (vd. `VII`), `title`, `char_count` (số ký tự toàn văn các con, tính xác định, để lập ngân sách token);
  - `Article`: `label` kiểu **chuỗi** đúng như văn bản viết (`"4"`, `"48a"`), là khóa tra cứu trong văn bản (đo: không có số Điều trùng trong một văn bản; 5 Điều có hậu tố chữ, đều ở Luật BHYT), `title`, `char_count`;
  - `Clause`: `label` chuỗi (`"1"`, `"3a"`; 6 Khoản có hậu tố chữ trong corpus), `text` đầy đủ, `chunk_ids` (danh sách vì Khoản dài bị tách nhiều chunk), `implicit` (Khoản ngầm định cấp Điều, `chunking_spec.md` mục 4), `has_table`, `raw_table` nếu có;
  - `Point`: `label`, `text`.
- Cạnh viện dẫn: `(:Clause|Point)-[:REFERS_TO {raw_text, kind}]->(:Article|Clause|Point)`.
  - `kind`: `single` | `range`; `raw_text`: đoạn viện dẫn nguyên văn (vd. "quy định tại Điều 72 của Luật này").
  - **Thẻ viện dẫn** ("key insight", quyết định đã chốt): khi truy vấn một Khoản/Điều, graph trả mỗi cạnh đi ra dưới dạng thẻ gồm `raw_text`, nhãn đích, tiêu đề Điều đích, `char_count`, trạng thái chưa mở. Toàn văn đích chỉ mở khi được yêu cầu, một bước; đích là Khoản/Điểm nhỏ có thể mở luôn. Thẻ hoàn toàn deterministic, không LLM.
  - "từ Điều X đến Điều Y" tách thành từng cạnh `kind=range` tới các Điều trong khoảng.
- Text đầy đủ chỉ ở `Clause`/`Point`; Điều/Chương/Phần chỉ giữ tiêu đề, text gộp khi truy vấn (quyết định: graph tự đủ để agent lấy ngữ cảnh mà không gọi lại Pinecone).

## 5. Nguồn dữ liệu và liên kết với Pinecone

- Dựng lại từ markdown bằng `chunking.parser.parse_markdown` (`DocumentTree`/`KhoanNode`); **không parse ngược từ breadcrumb chuỗi** và không sửa `chunking/`.
- `Chunk.chunk_id` = SHA-256 từ `source_document` + breadcrumb đầy đủ; graph không tự tính lại công thức ID mà đọc `chunk_id` từ `data/chunks/**/*.json` (đúng thứ đã embed vào Pinecone), không tạo lại chunk bằng splitter (tránh nạp tokenizer và tránh lệch với chunk đã embed).
- Khớp chunk ↔ đơn vị (quyết định đã chốt):
  - cắt hậu tố `( - Điểm …)?( (phần i/n))?` khỏi `Chunk.breadcrumb` để ra breadcrumb gốc, rồi so khớp **bằng nhau** (không dùng `startswith`: tiền tố nhầm "Khoản 1" với "Khoản 10"; đo ở Luật BHXH có 22 cặp tiền tố trùng) với `KhoanNode.breadcrumb_prefix + " - Khoản " + label`;
  - Khoản ngầm định (`khoan_number=None`): khớp với breadcrumb của chính Điều (không có phần `- Khoản`);
  - Khoản bị tách theo Điểm (đo ở Luật BHXH: 12 Khoản → 25 chunk, vd. Điều 2 Khoản 1 → 3 chunk): mọi chunk con cùng thuộc một `Clause`, `chunk_ids` sắp theo `split_index`;
  - front/back matter: khớp với tên văn bản hoặc `… - Chú thích sửa đổi (cuối văn bản)`, lưu ở `Document.front_chunk_ids`/`back_chunk_ids`;
  - `Point` không có `chunk_id` riêng; đi qua `Clause` cha.
- Mỗi chunk phải khớp **đúng một** đơn vị; chunk không khớp làm fail cả văn bản (thường là `data/chunks` cũ hơn markdown), không âm thầm bỏ qua.
- Điểm không có node trong `DocumentTree` (nằm trong `KhoanNode.content`): tách Điểm bằng regex `a)`, `b)`… trong `graph/`, không đổi parser của chunking.
- Front/back matter vào `Document.front_text`/`back_text`, không tạo node riêng.

## 6. Phân loại văn bản

- `kind` suy từ tên văn bản bằng quy tắc xác định (không LLM): Luật/Bộ luật → `goc`; Nghị định/Thông tư → `huong_dan`.
- `kind` quyết định cách xử lý "Điều N" trần (mục 7).

## 7. Trích và phân giải viện dẫn

- Phạm vi: văn bản nguồn là `Clause.text` và `Point.text`; cạnh đi từ node nhỏ nhất chứa viện dẫn.
- Quyết định (đã chốt trong brainstorm): **chỉ dùng quy tắc xác định, không LLM** ở bước phân giải. Căn cứ (mới xem 10 ca mẫu, chưa đo cả corpus): các mẫu "Điều N" trần trong NĐ đều trỏ sang văn bản mẹ (vd. NĐ Điều 8 "Điều 111, 112, 113, 114" là Bộ luật Lao động dù NĐ cũng có Điều số đó); tên NĐ nêu rõ văn bản mẹ.
- Nhận dạng chuỗi `[điểm …] [khoản …] Điều …`, danh sách `a, b và c` (mỗi phần tử một cạnh), khoảng "từ … đến …".
- Phân loại theo thứ tự:
  1. Trong cùng **câu** có viện dẫn nêu tên văn bản khác hoặc số hiệu (vd. "của Bộ luật Lao động", "Luật số 51/2024/QH15", "Luật Nhà giáo"): mọi viện dẫn trần cùng câu/danh sách là **ngoại**, chỉ đếm. Tên văn bản ở cuối danh sách áp dụng cho cả danh sách (vd. "…Điều 40, Điều 41; … Điều 46 của Bộ luật Lao động").
  2. "Điều này", "khoản X Điều này", đuôi "này" (Luật này/Nghị định này/Bộ luật này) → nội bộ.
  3. "Điều N" trần:
     - văn bản `goc` và đích tồn tại → nội bộ; đích không tồn tại → bỏ, đếm vào báo cáo;
     - văn bản `huong_dan` → **ngoại mặc định** (trỏ sang văn bản mẹ), không tạo cạnh.
- Phân giải tới mức nhỏ nhất đích tồn tại; đích Điều/Khoản/Điểm không có thật thì không tạo cạnh.
- Bỏ qua cạnh tự trỏ (vd. "Chính phủ quy định chi tiết Điều này") — không mang nội dung.
- Mức lưu: lưu đúng mức văn bản trỏ tới ("điểm a, b và c khoản 1 Điều 64" = 3 cạnh tới 3 Điểm; "Điều 65" = 1 cạnh tới Điều). Cộng dồn lên Điều khi truy vấn. **Không lưu closure** bắc cầu và không lưu cạnh Điều → Điều tổng hợp.
- Đánh đổi chấp nhận: mất viện dẫn nội bộ thật không có chữ "này" trong văn bản hướng dẫn; đo bằng 32 câu "Điều N" trần của NĐ (mục 11); chỉ khi mất đáng kể mới xét thêm tầng LLM (spec riêng, theo quy ước Groq của dự án).

## 8. Ghi vào Neo4j

- Driver chính thức `neo4j` (Python), phiên bản chốt khi implement bằng `context7`.
- Mỗi văn bản một transaction: xoá phần graph cũ của văn bản đó, `MERGE` theo `id`, ghi node cấu trúc → node con → cạnh `REFERS_TO`.
- Constraint `UNIQUE` trên `id` mỗi nhãn node; tạo trong bước khởi tạo, `IF NOT EXISTS`.
- Kết nối qua `config.py` (URI/user/password từ `.env`); package không tự đọc `.env`.
- Hạ tầng (quyết định đã chốt): Neo4j Community 5.x chạy bằng Docker local cho dev và integration test (marker `integration`); một database, constraint `UNIQUE`. Đưa Neo4j vào compose/CI là việc của người dùng trong PR `chore` riêng; `deploy/` và `.env.example` hiện chưa có Neo4j.
- Cấu trúc không có node tương ứng (vd. Phụ lục; corpus hiện tại không có Phụ lục hay Phần): **fail cả văn bản** và báo rõ, không bỏ qua âm thầm.

## 9. Kiểm tra sau ingest

- Số Điều/Khoản trong graph khớp `DocumentTree`.
- Mọi `chunk_id` của `Clause` có trong `data/chunks`; mọi chunk trong `data/chunks` của văn bản có trong đúng một `Clause` hoặc trong `front_chunk_ids`/`back_chunk_ids` (mục 5); chunk không khớp → fail văn bản.
- Không cạnh `REFERS_TO` tới node không tồn tại; không cạnh tự trỏ vào chính nó.
- Báo cáo mỗi văn bản: số node theo nhãn, số cạnh `REFERS_TO`, số viện dẫn ngoại, số bỏ vì đích không tồn tại, số "Điều N" trần bị loại ở văn bản hướng dẫn, số Khoản có text đúng `(được bãi bỏ)` (chỉ đếm, khớp cả dòng; không cờ `repealed` và không lọc trong truy vấn, quyết định đã chốt: ~3 Khoản ở Luật BHYT, chỉ ảnh hưởng đếm/liệt kê; thêm sau được vì chỉ là thuộc tính).

## 10. Thiết kế module và workflow

- Package `graph/`:
  - `models.py`: contract Pydantic v2 (node, cạnh, `Reference`, `GraphDocument`, báo cáo);
  - `builder.py`: `DocumentTree` + chunk JSON → `GraphDocument` (hierarchy, Điểm, `chunk_ids`);
  - `refs.py`: extractor regex và resolver (mục 7);
  - `store.py`: interface mỏng `GraphStore` + cài đặt Neo4j; test dùng fake qua interface;
  - `pipeline.py`: điều phối, kiểm tra mục 9, báo cáo.
- CLI Typer `tools/ingest_graph.py`: chạy từng văn bản hoặc cả thư mục; có chế độ `--dry-run` (dựng graph và báo cáo, không ghi Neo4j).
- Luồng: parse → build → trích và phân giải viện dẫn → kiểm tra → ghi Neo4j → báo cáo.
- Batch tuần tự; lỗi theo văn bản; full rebuild từng văn bản (không delta).
- Test: unit cho `refs`/`builder` trên mẫu thật; integration thật với Neo4j dùng marker `integration`.

## 11. Tiêu chí hoàn thành

- Graph dựng đủ 6 văn bản; kiểm tra mục 9 xanh; chạy lại cho graph y hệt.
- Đo trên mẫu viện dẫn gán nhãn tay: precision cạnh nội bộ ≥ 95%; báo cáo thêm recall để theo dõi, không là điều kiện.
- Toàn bộ 32 câu "Điều N" trần duy nhất trong NĐ (người dùng xem đúng/sai; quần thể nhỏ nên xem hết, không lấy mẫu) kiểm chứng giả định "mặc định ngoại" (mục 7); kết quả quyết định có cần tầng LLM không. Đây là kiểm chứng một lần, file mẫu để ở thư mục tạm ngoài repo; `data/eval/` là của riêng phần evaluation, graph không ghi vào đó.
- Truy vấn mẫu chạy được (có test với fake store và integration thật):
  - toàn văn một Điều theo `(short_name, label)`, vd. Điều 4 Luật TNCN trả đúng 22 Khoản theo `order`;
  - mục lục một Chương/Mục theo `order`, kèm `title` và `char_count`;
  - từ `chunk_id` → Khoản → Điều → các Khoản/Điều anh em, lên Mục/Chương;
  - từ Khoản → các Điều/Khoản nó viện dẫn và được viện dẫn bởi;
  - đếm Mục/Điều/Khoản/Điểm của một đơn vị.

## 12. Để lại cho spec sau

- Hợp đồng đọc graph cho retrieval/agent (các hàm đọc, kiểu input/output, giới hạn kích thước, chọn đường vào, mở thẻ viện dẫn). Spec này chỉ bảo đảm schema đủ phục vụ các truy vấn mẫu ở mục 11; nếu spec đọc phát hiện graph thiếu thuộc tính, sửa spec này và đặt lại `Draft`.
- Tầng LLM phân giải viện dẫn trần ở văn bản hướng dẫn: chỉ xét nếu kiểm chứng 32 câu (mục 11) cho thấy mất viện dẫn nội bộ đáng kể.
- Viện dẫn đa văn bản, entity/khái niệm (dạng G, mục 1.1).
