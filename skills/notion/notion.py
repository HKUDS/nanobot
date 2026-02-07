import os
import json
from notion_client import Client

def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

def get_client():
    cfg = load_config()
    api_key = cfg.get("api_key") or os.getenv("NOTION_API_KEY")
    if not api_key:
        raise ValueError("Notion API key not set in config.json or NOTION_API_KEY env var")
    return Client(auth=api_key)


def list_databases():
    client = get_client()
    result = client.databases.list()
    for db in result.get("results", []):
        title = "".join(t["plain_text"] for t in db.get("title", []))
        print(f"{db['id']}: {title}")

if __name__ == "__main__":
    list_databases()
