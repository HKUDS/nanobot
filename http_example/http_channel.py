import json
import urllib.request

url = "http://127.0.0.1:18789/chat"
token = "347454056151ad835bd40cec64ed5ff73669fcf66e11a1aa"

payload = {
    "session_id": "user-001",
    "message": "昨天我们有说什么你还记得吗",
    "stream": True
}

req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    },
    method="POST",
)

with urllib.request.urlopen(req, timeout=120) as resp:
    for raw in resp:
        line = raw.decode("utf-8").strip()
        if not line:
            continue
        print(line)