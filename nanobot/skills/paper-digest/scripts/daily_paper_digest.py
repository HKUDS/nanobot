#!/usr/bin/env python3
"""Fetch papers from arXiv and return LLM-friendly JSON output."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
UTC = timezone.utc
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import httpx

# 核心架构与设计
# 本工具采用的是 “数据检索 -> 格式转化 -> 消息推送” 的线性管道流程。
# 数据源：arXiv API，通过 Atom (XML) 协议提供数据。
# 数据模型：PaperKeyValue 类，定义了每一篇论文必须包含的字段（如 title, abstract, doi, url, authors 等）。
# 输出格式：标准 JSON，保持 key-value 结构，方便后续自动化处理或人工阅读。

# 数据源
ARXIV_API = "https://export.arxiv.org/api/query"



# A.参数初始化 ( parse_args & load_config )
# 程序优先读取命令行参数（如 --keyword, --max-papers），
# 同时支持从 ~/.nanobot/paper_digest.json 读取持久化配置（如 feishu_webhook）。
# 时间范围演算：如果用户没指定日期，程序会自动计算 today - days_back（default 过去7天）作为搜索窗口。


# 数据模型
@dataclass
class PaperKeyValue:
    title: str
    abstract: str
    doi: str
    paper_id: str
    year: int | None
    publication_date: str
    venue: str
    url: str
    open_access_pdf: str
    is_open_access: bool
    citations: int | None
    influential_citations: int | None
    references: int | None
    fields_of_study: list[str]
    authors: list[str]
    tldr: str

# 命令行中的参数
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="arXiv daily paper digest (JSON key-value)")
    parser.add_argument("--config", type=Path, default=None, help="Optional JSON config path")
    parser.add_argument("--keyword", type=str, default="AI application development", help="Search keyword")
    parser.add_argument("--from-date", type=str, default="", help="Start date YYYY-MM-DD")
    parser.add_argument("--to-date", type=str, default="", help="End date YYYY-MM-DD")
    parser.add_argument("--days-back", type=int, default=7, help="Use today - N days if from-date is empty")
    parser.add_argument("--max-papers", type=int, default=5, help="Output quantity")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON file")
    parser.add_argument(
        "--llm-abstract-max-chars",
        type=int,
        default=1200,
        help="Max abstract chars per paper in LLM output",
    )
    parser.add_argument("--request-timeout", type=float, default=30.0, help="HTTP timeout seconds")
    return parser.parse_args()

# 配置文件内的参数
def load_config(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# C. 数据清洗 ( _paper_from_entry )
# 将原始的 XML 节点抓取后，封装进 PaperKeyValue 容器：

# 日期处理：将 2026-04-08T12:00:00Z 截断并标准化为 2026-04-08。
# 作者/领域列表：将嵌套的作者节点和分类节点展平为简单的字符串列表。

def _paper_from_entry(entry: ET.Element, ns: dict[str, str]) -> PaperKeyValue:
    title = _text(entry.find("atom:title", ns))
    abstract = _text(entry.find("atom:summary", ns))
    paper_url = _text(entry.find("atom:id", ns))
    published_raw = _text(entry.find("atom:published", ns))

    publication_date = published_raw[:10] if published_raw else ""
    year: int | None = None
    if publication_date:
        try:
            year = int(publication_date[:4])
        except ValueError:
            year = None

    doi = _text(entry.find("arxiv:doi", ns))
    paper_id = paper_url.rstrip("/").split("/")[-1] if paper_url else ""

    authors: list[str] = []
    for author in entry.findall("atom:author", ns):
        name = _text(author.find("atom:name", ns))
        if name:
            authors.append(name)

    categories: list[str] = []
    for cat in entry.findall("atom:category", ns):
        term = (cat.attrib.get("term") or "").strip()
        if term:
            categories.append(term)

    pdf_url = ""
    for link in entry.findall("atom:link", ns):
        href = (link.attrib.get("href") or "").strip()
        title_attr = (link.attrib.get("title") or "").strip().lower()
        link_type = (link.attrib.get("type") or "").strip().lower()
        if title_attr == "pdf" or href.endswith(".pdf") or "pdf" in link_type:
            pdf_url = href
            break

    return PaperKeyValue(
        title=title,
        abstract=abstract,
        doi=doi,
        paper_id=paper_id,
        year=year,
        publication_date=publication_date,
        venue="arXiv",
        url=paper_url,
        open_access_pdf=pdf_url,
        is_open_access=True,
        citations=None,
        influential_citations=None,
        references=None,
        fields_of_study=categories,
        authors=authors,
        tldr="",
    )

# B. 数据抓取与解析 ( fetch_arxiv_papers )
# 这是代码最复杂的部分，涉及 XML 的深层解析：
# 分页请求：arXiv 的单个请求返回数量有限。代码通过 start 参数进行循环分页处理，确保在宽泛的时间范围内能搜到足够的论文。
# XML 命名空间处理：arXiv 的返回格式包含 atom 和 arxiv 两个命名空间。代码通过 ns 字典精确匹配标签
# （如 atom:title 获取标题，arxiv:doi 获取 DOI）。
# 智能提取 PDF 链接：在多个 <link> 标签中，代码会根据 title="pdf" 属性或后缀名自动筛选出最准确的 Open Access PDF 地点。

def fetch_arxiv_papers(
    client: httpx.Client,
    keyword: str,
    from_date: datetime,
    to_date: datetime,
    max_papers: int,
) -> list[PaperKeyValue]:
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    papers: list[PaperKeyValue] = []

    # Fetch in pages so date filtering still returns enough papers.
    page_size = max(max_papers * 4, 20)
    for start in range(0, 200, page_size):
        params = {
            "search_query": f"all:{keyword}",
            "start": str(start),
            "max_results": str(page_size),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        resp = client.get(ARXIV_API, params=params)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", ns)
        if not entries:
            break

        for entry in entries:
            published_raw = _text(entry.find("atom:published", ns))
            published_dt = _parse_date(published_raw)
            if published_dt is None:
                continue
            if published_dt < from_date or published_dt > to_date:
                continue
            papers.append(_paper_from_entry(entry, ns))
            if len(papers) >= max_papers:
                return papers

    return papers


def build_llm_output(
    keyword: str,
    from_date: datetime,
    to_date: datetime,
    papers: list[PaperKeyValue],
    abstract_max_chars: int,
) -> dict[str, Any]:
    """Build compact, LLM-friendly payload from raw paper records."""
    items: list[dict[str, Any]] = []
    for paper in papers:
        summary = paper.abstract.strip().replace("\n", " ")
        if abstract_max_chars > 0 and len(summary) > abstract_max_chars:
            summary = summary[:abstract_max_chars].rstrip() + "..."
        items.append(
            {
                "title": paper.title,
                "summary": summary,
                "url": paper.url,
                "pdf": paper.open_access_pdf,
                "publication_date": paper.publication_date,
                "authors": paper.authors,
                "fields_of_study": paper.fields_of_study,
            }
        )

    return {
        "type": "paper_digest_for_llm",
        "keyword": keyword,
        "time_range": {
            "from_date": from_date.date().isoformat(),
            "to_date": to_date.date().isoformat(),
        },
        "count": len(items),
        "papers": items,
    }


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)

    keyword = (cfg.get("keyword") or args.keyword).strip()
    max_papers = int(cfg.get("max_papers") or args.max_papers)
    timeout_sec = float(cfg.get("request_timeout_sec") or args.request_timeout)

    now = datetime.now(UTC)
    to_date_text = (cfg.get("to_date") or args.to_date).strip()
    from_date_text = (cfg.get("from_date") or args.from_date).strip()
    days_back = int(cfg.get("days_back") or args.days_back)

    to_date = _parse_date(f"{to_date_text}T23:59:59+00:00") if to_date_text else now
    if to_date is None:
        raise ValueError("Invalid to-date format, expected YYYY-MM-DD")

    if from_date_text:
        from_date = _parse_date(f"{from_date_text}T00:00:00+00:00")
        if from_date is None:
            raise ValueError("Invalid from-date format, expected YYYY-MM-DD")
    else:
        from_date = to_date - timedelta(days=days_back)

    abstract_max_chars = int(cfg.get("llm_abstract_max_chars") or args.llm_abstract_max_chars)

    with httpx.Client(timeout=timeout_sec) as client:
        papers = fetch_arxiv_papers(
            client=client,
            keyword=keyword,
            from_date=from_date,
            to_date=to_date,
            max_papers=max_papers,
        )

        result = {
            "keyword": keyword,
            "from_date": from_date.date().isoformat(),
            "to_date": to_date.date().isoformat(),
            "count": len(papers),
            "papers": [asdict(p) for p in papers],
        }
        llm_payload = build_llm_output(
            keyword=keyword,
            from_date=from_date,
            to_date=to_date,
            papers=papers,
            abstract_max_chars=abstract_max_chars,
        )

        output = args.output or Path.cwd() / f"paper_digest_{datetime.now(UTC).strftime('%Y%m%d')}.json"
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Digest saved: {output}")

        # Print LLM-oriented payload to stdout for tool-chaining.
        print(json.dumps(llm_payload, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
