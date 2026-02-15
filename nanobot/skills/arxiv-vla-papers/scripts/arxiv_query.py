#!/usr/bin/env python3
"""
Query arXiv for latest Vision-Language-Action (VLA) papers.

Supports filtering by:
- Date range (today, 2 days, 1 week)
- Categories (cs.AI, cs.CV, cs.HC, cs.LG, cs.RO)
- Keywords (vision-language-action, robotic manipulation, navigation)
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen

ARXIV_API_BASE = "http://export.arxiv.org/api/query"

# Category mappings
CATEGORIES = {
    "ai": "cs.AI",
    "cv": "cs.CV",
    "hci": "cs.HC",
    "ml": "cs.LG",
    "robotics": "cs.RO",
}

# Default categories for VLA papers
DEFAULT_CATEGORIES = ["cs.AI", "cs.CV", "cs.HC", "cs.LG", "cs.RO"]

# Keywords for VLA papers
VLA_KEYWORDS = [
    "vision-language-action",
    "vision language action",
    "VLA",
    "robotic manipulation",
    "robot manipulation",
    "language-conditioned",
    "language conditioned",
    "instruction following",
    "embodied AI",
    "embodied intelligence",
]


def parse_date_range(days: int) -> tuple[str, str]:
    """Calculate date range for arXiv query."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    # arXiv uses YYYYMMDDHHMMSS format
    return start_date.strftime("%Y%m%d%H%M%S"), end_date.strftime("%Y%m%d%H%M%S")


def build_query(
    keywords: list[str],
    categories: list[str],
    date_range: Optional[Tuple[str, str]] = None,
    max_results: int = 50,
) -> str:
    """Build arXiv API query URL."""
    # Combine keywords with OR
    keyword_query = " OR ".join([f'all:"{kw}"' for kw in keywords])
    
    # Combine categories with OR
    category_query = " OR ".join([f'cat:"{cat}"' for cat in categories])
    
    # Combine with AND
    query = f"({keyword_query}) AND ({category_query})"
    
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    
    if date_range:
        params["submittedDate"] = f"{date_range[0]}000000*{date_range[1]}235959"
    
    return f"{ARXIV_API_BASE}?{urlencode(params)}"


def fetch_papers(url: str) -> list[dict[str, Any]]:
    """Fetch papers from arXiv API and parse XML."""
    try:
        with urlopen(url, timeout=30) as response:
            xml_content = response.read().decode("utf-8")
    except Exception as e:
        print(f"Error fetching from arXiv: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Use xml.etree.ElementTree for robust parsing
    try:
        import xml.etree.ElementTree as ET
    except ImportError:
        # Fallback to regex if ElementTree not available
        import re
        return _parse_xml_regex(xml_content)
    
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        # Fallback to regex if XML parsing fails
        import re
        return _parse_xml_regex(xml_content)
    
    # Handle namespaces
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    
    papers = []
    entries = root.findall('atom:entry', ns)
    
    for entry in entries:
        # Extract title
        title_elem = entry.find('atom:title', ns)
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Unknown"
        title = ' '.join(title.split())  # Normalize whitespace
        
        # Extract authors
        authors = []
        for author in entry.findall('atom:author', ns):
            name_elem = author.find('atom:name', ns)
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())
        
        # Extract abstract
        summary_elem = entry.find('atom:summary', ns)
        abstract = summary_elem.text.strip() if summary_elem is not None and summary_elem.text else ""
        abstract = ' '.join(abstract.split())
        
        # Extract ID and URL
        id_elem = entry.find('atom:id', ns)
        paper_id = id_elem.text if id_elem is not None and id_elem.text else ""
        arxiv_id = paper_id.split("/")[-1] if "/" in paper_id else ""
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""
        abs_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""
        
        # Extract published date
        published_elem = entry.find('atom:published', ns)
        published = published_elem.text if published_elem is not None and published_elem.text else ""
        
        # Extract categories
        categories = []
        for category in entry.findall('atom:category', ns):
            term = category.get('term')
            if term:
                categories.append(term)
        
        papers.append({
            "id": arxiv_id,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "published": published,
            "categories": categories,
            "pdf_url": pdf_url,
            "abs_url": abs_url,
        })
    
    return papers


def _parse_xml_regex(xml_content: str) -> list[dict[str, Any]]:
    """Fallback regex-based XML parsing."""
    import re
    
    papers = []
    entry_pattern = r'<entry>(.*?)</entry>'
    entries = re.findall(entry_pattern, xml_content, re.DOTALL)
    
    for entry in entries:
        # Extract title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', entry, re.DOTALL)
        title = title_match.group(1).strip() if title_match else "Unknown"
        title = re.sub(r'\s+', ' ', title)
        
        # Extract authors
        author_pattern = r'<name>(.*?)</name>'
        authors = re.findall(author_pattern, entry)
        
        # Extract abstract
        abstract_match = re.search(r'<summary[^>]*>(.*?)</summary>', entry, re.DOTALL)
        abstract = abstract_match.group(1).strip() if abstract_match else ""
        abstract = re.sub(r'\s+', ' ', abstract)
        
        # Extract ID and URL
        id_match = re.search(r'<id>(.*?)</id>', entry)
        paper_id = id_match.group(1) if id_match else ""
        arxiv_id = paper_id.split("/")[-1] if "/" in paper_id else ""
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""
        abs_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""
        
        # Extract published date
        published_match = re.search(r'<published>(.*?)</published>', entry)
        published = published_match.group(1) if published_match else ""
        
        # Extract categories
        category_pattern = r'term="([^"]+)"'
        categories = re.findall(category_pattern, entry)
        
        papers.append({
            "id": arxiv_id,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "published": published,
            "categories": categories,
            "pdf_url": pdf_url,
            "abs_url": abs_url,
        })
    
    return papers


def main():
    parser = argparse.ArgumentParser(
        description="Query arXiv for latest VLA papers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help="Maximum number of results (default: 20)",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=DEFAULT_CATEGORIES,
        help=f"Categories to search (default: {DEFAULT_CATEGORIES})",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=VLA_KEYWORDS,
        help="Additional keywords to search",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--no-date-filter",
        action="store_true",
        help="Don't filter by date (search all papers)",
    )
    
    args = parser.parse_args()
    
    # Calculate date range
    date_range = None if args.no_date_filter else parse_date_range(args.days)
    
    # Build and execute query
    query_url = build_query(
        keywords=args.keywords,
        categories=args.categories,
        date_range=date_range,
        max_results=args.max_results,
    )
    
    papers = fetch_papers(query_url)
    
    if args.json:
        print(json.dumps(papers, indent=2, ensure_ascii=False))
    else:
        # Human-readable output
        print(f"Found {len(papers)} papers from the last {args.days} days\n")
        for i, paper in enumerate(papers, 1):
            print(f"{i}. {paper['title']}")
            print(f"   Authors: {', '.join(paper['authors'][:3])}{' et al.' if len(paper['authors']) > 3 else ''}")
            print(f"   Published: {paper['published'][:10] if paper['published'] else 'Unknown'}")
            print(f"   URL: {paper['abs_url']}")
            print(f"   Abstract: {paper['abstract'][:200]}...")
            print()


if __name__ == "__main__":
    main()
