# Sen Local Setup

Tài liệu này chuẩn bị repo để phát triển Sen, D's Agent 01, trên nền Nanobot + GBrain.

Mục tiêu là giữ runtime thật an toàn: repo chỉ chứa tài liệu và config mẫu. Config thật vẫn nằm ngoài repo.

## Bản đồ local

| Thành phần | Đường dẫn / giá trị |
| --- | --- |
| Sen config thật | `~/.nanobot/sen/config.json` |
| Sen workspace | `~/.nanobot/sen/workspace` |
| GBrain repo | `~/gbrain` |
| Brain corpus | `~/brain` |
| GBrain MCP command | `/Users/dzungbui/.bun/bin/gbrain serve` |
| Provider chính | `openrouter` |
| Model chính | `moonshotai/kimi-k2.6` |

## Nguyên tắc an toàn

- Không commit `~/.nanobot/sen/config.json`.
- Không ghi API key vào repo.
- Không in API key ra terminal, log, docs hoặc issue.
- Không sửa `~/brain`, `~/gbrain`, `~/.zshrc` khi chỉ đang chuẩn bị repo.
- Config mẫu chỉ dùng placeholder như `${OPENROUTER_API_KEY}`.

## Config mẫu

Config mẫu nằm ở:

```text
examples/sen/config.example.json
```

File này mô tả các phần chính:

- `agents.defaults.workspace`: trỏ tới workspace riêng của Sen.
- `agents.defaults.provider`: dùng `openrouter`.
- `agents.defaults.model`: dùng `moonshotai/kimi-k2.6`.
- `providers.openrouter.apiKey`: dùng biến môi trường `${OPENROUTER_API_KEY}`, không ghi key thật.
- `tools.mcpServers.gbrain`: chạy GBrain MCP bằng command local.

Để dùng thật, hãy copy nội dung mẫu vào config thật bằng tay, rồi tự điền hoặc export secret ngoài repo.

Ví dụ biến môi trường:

```bash
export OPENROUTER_API_KEY="REPLACE_WITH_YOUR_OPENROUTER_KEY"
```

Không commit file shell chứa key.

## Khởi tạo instance Sen nếu chưa có

Nếu `~/.nanobot/sen/config.json` chưa tồn tại, có thể tạo instance riêng bằng:

```bash
nanobot onboard --config ~/.nanobot/sen/config.json --workspace ~/.nanobot/sen/workspace
```

Sau đó merge các phần cần thiết từ `examples/sen/config.example.json` vào config thật.

Không thay toàn bộ config thật nếu trong đó đã có setting khác cần giữ.

## Smoke test để Dũng tự chạy

Kiểm tra config mẫu là JSON hợp lệ:

```bash
python3 -m json.tool examples/sen/config.example.json
```

Kiểm tra Nanobot đọc được config thật và gọi một lượt ngắn:

```bash
nanobot agent \
  --config ~/.nanobot/sen/config.json \
  --workspace ~/.nanobot/sen/workspace \
  -m "Reply with: Sen ready"
```

Nếu muốn test MCP GBrain, hỏi Sen một câu ngắn cần dùng GBrain. Ví dụ:

```bash
nanobot agent \
  --config ~/.nanobot/sen/config.json \
  --workspace ~/.nanobot/sen/workspace \
  -m "Check whether the GBrain MCP tools are available. Do not modify files."
```

## Khi có lỗi thường gặp

Nếu lỗi provider hoặc auth:

- Kiểm tra biến môi trường `OPENROUTER_API_KEY`.
- Kiểm tra `providers.openrouter.apiKey` đang là `${OPENROUTER_API_KEY}` hoặc key thật nằm ngoài repo.
- Kiểm tra model là `moonshotai/kimi-k2.6`.

Nếu lỗi MCP:

- Kiểm tra command `/Users/dzungbui/.bun/bin/gbrain` có tồn tại.
- Kiểm tra `~/gbrain` và `~/brain` có sẵn trên máy.
- Không sửa dữ liệu trong `~/brain` hoặc `~/gbrain` chỉ để debug config.
