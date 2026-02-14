#!/usr/bin/env python3
"""
User Profile Enrichment for Sandman.
Runs semantic searches on recent sessions to extract user preferences, habits, etc.
Generates proposals for USER.md updates.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime

# Queries from design document
QUERIES = [
    "user preferences and likes dislikes",
    "personal context identity background",
    "habits patterns routines",
    "current priorities and active goals",
    "values beliefs worldview",
    "frustrations pain points friction"
]

def run_semantic_search(query, top_k=5, min_score=0.4, dry_run=False):
    """Run a semantic search query using load-context-semantic.py"""
    cmd = [
        'python3', 'scripts/load-context-semantic.py', query,
        '--top-k', str(top_k),
        '--min-score', str(min_score),
        '--json'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            if dry_run:
                print(f"No results for query: {query}", file=sys.stderr)
            return []
        
        return json.loads(result.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        if dry_run:
            print(f"Error running search for {query}: {e}", file=sys.stderr)
        return []

def extract_user_facts(results, dry_run=False):
    """Extract concrete user facts from search results."""
    facts = {
        'Current Priorities': [],
        'Core Systems & Interests': [],
        'Temperament': [],
        'Values': [],
        'Project Themes': [],
        'Communication Preferences': [],
        'Working Style': []
    }
    
    # Simple keyword-based categorization (could be more sophisticated)
    category_keywords = {
        'Current Priorities': ['priority', 'focus', 'important', 'goal'],
        'Core Systems & Interests': ['interested', 'system', 'technology', 'expertise'],
        'Temperament': ['direct', 'patient', 'organized', 'creative', 'temperament'],
        'Values': ['value', 'believe', 'principle', 'ethics'],
        'Project Themes': ['project', 'work on', 'developing'],
        'Communication Preferences': ['prefer', 'like to', 'communication', 'style'],
        'Working Style': ['workflow', 'process', 'approach', 'method']
    }
    
    for query_results in results:
        for result in results[query_results]:
            text = result.get('content', '')
            if len(text) < 20:  # Skip very short snippets
                continue
            
            # Check for concrete facts
            if any(phrase in text.lower() for phrase in [
                'i prefer', 'i like', 'i tend to', 'i value', 'i believe',
                'i\'m focused on', 'i work on', 'i\'m building', 'i\'m', 'i have'
            ]):
                categorized = False
                for category, keywords in category_keywords.items():
                    if any(keyword in text.lower() for keyword in keywords):
                        facts[category].append({
                            'text': text[:200],  # Truncate if needed
                            'source': result.get('source', ''),
                            'query': query_results
                        })
                        categorized = True
                        break
                
                if not categorized:
                    # Default to Core Systems if not classified
                    facts['Core Systems & Interests'].append({
                        'text': text[:200],
                        'source': result.get('source', ''),
                        'query': query_results
                    })
    
    return facts

def generate_proposal_report(facts, dry_run=False):
    """Generate structured proposal report."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    file_path = f'memory/sandman/{today_str}-user_enrichment_proposals.md'
    
    report_lines = [
        "# USER.md Enrichment Proposals",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Proposed USER.md Updates",
        ""
    ]
    
    for section, items in facts.items():
        if not items:
            continue
            
        report_lines.append(f"### {section}")
        
        for i, item in enumerate(items[:3], 1):  # Limit to 3 per section
            report_lines.append(f"**Proposed Addition {i}:**")
            report_lines.append(f"```{item['text']}```")
            report_lines.append(f"**Evidence:** From {item['source'][:50]}... (query: {item['query']})")
            report_lines.append("")
    
    if not any(facts.values()):
        report_lines.append("No new user insights found in recent sessions.")
    
    report_lines.extend([
        "## Application Instructions",
        "",
        "1. Review each proposed addition for accuracy and relevance",
        "2. Ensure it doesn't conflict with existing USER.md content", 
        "3. Manually integrate appropriate facts into USER.md sections",
        "4. Delete this proposal file after applying changes",
        "",
        "**Note:** These are proposals only - human review required for all changes to USER.md."
    ])
    
    content = "\n".join(report_lines)
    
    if dry_run:
        print("DRY RUN MODE:")
        print(content[:1000] + "..." if len(content) > 1000 else content)
        print(f"Would write to: {file_path}")
    else:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Report written to: {file_path}")
        except Exception as e:
            print(f"Error writing report: {e}", file=sys.stderr)
            return False
    
    return True

def main():
    parser = argparse.ArgumentParser(description="Enrich USER.md with semantic search insights")
    parser.add_argument('--dry-run', action='store_true', help="Test mode - don't write files")
    parser.add_argument('--top-k', type=int, default=5, help="Results per query")
    parser.add_argument('--min-score', type=float, default=0.4, help="Minimum similarity score")
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("Running in DRY RUN mode")
    
    # Run all semantic searches
    all_results = {}
    for query in QUERIES:
        if args.dry_run:
            print(f"Searching: {query}")
        results = run_semantic_search(query, args.top_k, args.min_score, args.dry_run)
        all_results[query] = results
    
    if not any(all_results.values()):
        print("No search results found", file=sys.stderr)
        return 1
    
    # Extract user facts
    facts = extract_user_facts(all_results, args.dry_run)
    
    # Generate proposal report
    success = generate_proposal_report(facts, args.dry_run)
    
    return 0 if success else 1

if __name__ == '__main__':
    sys.exit(main())