import json
from pathlib import Path

with open("/Users/shaozhenzhou/.nanobot/config.json", "r") as f:
    config = json.load(f)

token = config.get("paddleocr", {}).get("token")

file_path = "tests/pic/初审界面.png"
with open(file_path, "rb") as f:
    file_data = __import__("base64").b64encode(f.read()).decode("ascii")

headers = {
    "Authorization": f"token {token}",
    "Content-Type": "application/json"
}

payload = {
    "file": file_data,
    "fileType": 1,
}

response = __import__("requests").post(
    "https://k7b3acgclfxeacxe.aistudio-app.com/layout-parsing",
    json=payload,
    headers=headers,
    timeout=60
)

print("Status Code:", response.status_code)
print("Response Text:", response.text[:500])
