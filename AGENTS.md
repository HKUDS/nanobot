# AGENTS.md

## Mục tiêu repo trong workspace này

Repo này đang được chuẩn bị để phát triển Sen, D's Agent 01, dựa trên Nanobot và GBrain.

Ưu tiên hiện tại:

- Giữ Nanobot là runtime agent nền.
- Dùng GBrain qua MCP để đọc/làm việc với tri thức cá nhân.
- Tách rõ tài liệu, config mẫu, runtime thật và dữ liệu thật.
- Làm bản đơn giản chạy được trước, dễ kiểm tra, dễ sửa.

## Ranh giới an toàn

Không được tự ý sửa các đường dẫn thật sau:

- `~/.nanobot/sen/config.json`
- `~/.nanobot/sen/workspace`
- `~/gbrain`
- `~/brain`
- `~/.zshrc`

Không được in, ghi, commit hoặc sao chép API key, private key, token, secret hoặc dữ liệu nhạy cảm.

Khi cần minh họa config, chỉ dùng placeholder như `${OPENROUTER_API_KEY}` hoặc `REPLACE_ME`.

## Cách làm việc với Sen

- Tài liệu riêng của Sen đặt trong `docs/sen/`.
- Config mẫu riêng của Sen đặt trong `examples/sen/`.
- Không đọc config thật chỉ để viết docs hoặc example.
- Không chạy command có thể thay đổi runtime thật nếu Dũng chưa xác nhận rõ.
- Nếu cần smoke test, ưu tiên lệnh đọc-only hoặc lệnh một lần dùng `--config` và `--workspace` rõ ràng.

## Local paths đã biết

Các path này dùng để viết tài liệu và ví dụ, không dùng để tự sửa runtime:

- Sen config thật: `~/.nanobot/sen/config.json`
- Sen workspace: `~/.nanobot/sen/workspace`
- GBrain repo: `~/gbrain`
- Brain corpus: `~/brain`
- GBrain MCP command: `/Users/dzungbui/.bun/bin/gbrain serve`
- Provider chính: `openrouter`
- Model chính: `moonshotai/kimi-k2.6`

## Lệnh repo

Không tự bịa lệnh test/build. Đọc `README.md`, `docs/`, `pyproject.toml` và file liên quan trước khi chạy.

Các lệnh thường dùng trong repo Nanobot:

```bash
python3 -m pytest
ruff check .
```

Với thay đổi chỉ gồm tài liệu/config mẫu, kiểm tra tối thiểu nên là:

```bash
python3 -m json.tool examples/sen/config.example.json
```
