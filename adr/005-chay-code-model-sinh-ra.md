# ADR 005 — Chạy code do model sinh ra: bắt buộc chọn `docker` hoặc `local`, không có mặc định

Ngày: 2026-10-30 · Trạng thái: đề xuất, chờ Hoài duyệt · Liên quan: ADR 004, AGENT.md luật 7

## Bối cảnh

Tool `run_python` chạy code model viết. Ở EXP-20261029-01 việc này do Claude Code làm, có hộp xin
quyền. Harness mới chạy không có người duyệt từng lệnh.

Đây là việc chạm **an toàn thông tin**, mảng Hoài ghi là không làm. Ghi rõ ở đây để Hoài quyết có
ý thức, không để mặc định quyết thay.

## Quyết định

`executor.kind` là field **bắt buộc** trong config, không có mặc định:

| Kind | Cách chạy | Chặn được gì | Không chặn được gì |
| --- | --- | --- | --- |
| `docker` | `docker run --rm --network none`, `data/` mount **read-only**, `work/` mount read-write, `src/` read-only | gọi mạng, ghi vào `public_test/`/`train/`, đọc file khác trên máy | ăn CPU/RAM (có `--memory`, `--cpus`) |
| `local` | `subprocess` của Python, `cwd = work/`, env chỉ gồm biến cần thiết (không có API key), timeout | lộ API key qua env | **mọi thứ khác**: code đọc/ghi bất kỳ đâu user hiện tại có quyền, gọi mạng |

Tool đọc/ghi file của harness (`read_file`, `write_file`) luôn kiểm đường dẫn nằm trong `data/` hoặc
`work/`, ở cả hai kind. Nhưng `run_python` ở kind `local` **vượt qua được** kiểm này, vì code Python
tự mở file.

## Đánh đổi kinh điển

Đây là **sandboxing / principle of least privilege**: code không tin được thì chạy với quyền ít
nhất đủ dùng. Docker cho cô lập ở tầng kernel namespace; `local` chỉ cô lập bằng quy ước. Giá của
docker: cần daemon chạy, image có `pandas` + `openpyxl`, và mỗi lần chạy thêm ~1 s khởi container.

## Vì sao không có mặc định

Mặc định `local` là chọn hộ Hoài một rủi ro an toàn; mặc định `docker` thì hỏng ngay trên máy hiện
tại (2026-10-30: `docker info` treo > 120 s, daemon không trả lời). Bắt chọn tường minh thì config
nói rõ đang chạy theo kiểu nào.

## Khuyến nghị

`docker` cho mọi lần chạy với model chưa thử. `local` chỉ khi đang debug harness với vài shop và
đã đọc transcript.

## Bổ sung: file đáp án gold

`train/` để `answers.jsonl` và `split/*_answers.jsonl` ngay cạnh dữ liệu. Tool chỉ lộ `rulebook.md`,
`calendar.csv`, `data/`; `docker` chỉ mount đúng ba mục đó. Ở `local`, script **đọc được** file gold
nếu tự mở đường dẫn tuyệt đối — thêm một lý do để calibration trên train chỉ chạy bằng `docker`.
