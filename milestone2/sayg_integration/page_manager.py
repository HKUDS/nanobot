import threading
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import json
import hashlib

class PageManager:
    def __init__(self, pages_dir: Path):
        self.pages_dir = Path(pages_dir)
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._page_index_path = self.pages_dir / "page_index.jsonl"
        self._init_index()

    def _init_index(self):
        if not self._page_index_path.exists():
            self._page_index_path.touch()

    def _get_all_pages(self) -> List[Dict]:
        if self._page_index_path.stat().st_size == 0:
            return []
        pages = []
        with open(self._page_index_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    pages.append(json.loads(line))
        return pages

    def _save_page_meta(self, page_meta: Dict):
        with self._lock:
            with open(self._page_index_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(page_meta, ensure_ascii=False) + '\n')

    def create_page(self, page_id: str, title: str, initial_content: str = "") -> str:
        page_path = self.pages_dir / f"{page_id}.json"
        page_meta = {
            "page_id": page_id,
            "title": title,
            "created_at": datetime.now().isoformat() + "Z",
            "updated_at": datetime.now().isoformat() + "Z",
            "content_hash": hashlib.md5(initial_content.encode()).hexdigest()
        }

        page_data = {
            "meta": page_meta,
            "content": initial_content
        }

        with self._lock:
            page_path.write_text(json.dumps(page_data, ensure_ascii=False), encoding='utf-8')
            self._save_page_meta(page_meta)

        return page_id

    def update_page(self, page_id: str, content: str, append: bool = False) -> bool:
        page_path = self.pages_dir / f"{page_id}.json"
        if not page_path.exists():
            return False

        with self._lock:
            page_data = json.loads(page_path.read_text(encoding='utf-8'))

            if append:
                page_data["content"] += "\n" + content
            else:
                page_data["content"] = content

            page_data["meta"]["updated_at"] = datetime.now().isoformat() + "Z"
            page_data["meta"]["content_hash"] = hashlib.md5(page_data["content"].encode()).hexdigest()

            page_path.write_text(json.dumps(page_data, ensure_ascii=False), encoding='utf-8')

        return True

    def get_page(self, page_id: str) -> Optional[Dict]:
        page_path = self.pages_dir / f"{page_id}.json"
        if not page_path.exists():
            return None
        return json.loads(page_path.read_text(encoding='utf-8'))

    def search_pages(self, query: str, top_k: int = 5) -> List[Dict]:
        results = []
        keywords = query.lower().split()

        all_pages = self._get_all_pages()
        for page_meta in all_pages:
            page = self.get_page(page_meta["page_id"])
            if page and any(kw in page["content"].lower() for kw in keywords):
                results.append(page)
                if len(results) >= top_k:
                    break

        return results

    def list_pages(self) -> List[Dict]:
        return self._get_all_pages()

    def delete_page(self, page_id: str) -> bool:
        page_path = self.pages_dir / f"{page_id}.json"
        if page_path.exists():
            with self._lock:
                page_path.unlink()
            return True
        return False

    def count(self) -> int:
        return len(self._get_all_pages())
