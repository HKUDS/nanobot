#!/usr/bin/env python3
"""
MEMORY.md Compression for Sandman.
Periodically compresses old/redundant content in MEMORY.md while preserving critical information.
Archives old details and creates compression report.
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

def count_tokens(text):
    """Rough token count approximation (words/0.75)."""
    words = len(re.findall(r'\b\w+\b', text))
    return int(words / 0.75)

def read_memory_file():
    """Read current MEMORY.md content."""
    memory_file = Path('/home/deva/shared/MEMORY.md')
    if not memory_file.exists():
        print("MEMORY.md not found", file=sys.stderr)
        return None
    
    try:
        with open(memory_file, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Error reading MEMORY.md: {e}", file=sys.stderr)
        return None

def parse_memory_sections(content):
    """Parse MEMORY.md into sections."""
    sections = {}
    current_section = None
    current_lines = []
    
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('## '):
            if current_section:
                sections[current_section] = '\n'.join(current_lines).strip()
            current_section = line[3:].strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    
    if current_section:
        sections[current_section] = '\n'.join(current_lines).strip()
    
    return sections

def identify_protected_sections(sections):
    """Identify sections that should never be compressed."""
    protected_patterns = [
        r".*\bidentity\b.*",
        r".*\score patterns\b.*",
        r".*\bvalues\b.*",
        r".*\bworldview\b.*",
        r".*\bcritical decisions\b.*",
        r".*\bactive projects\b.*"
    ]
    
    protected = {}
    compressible = {}
    
    for section_name, section_content in sections.items():
        is_protected = False
        for pattern in protected_patterns:
            if re.search(pattern, section_name.lower()) or '[KEEP]' in section_content or '[CORE]' in section_content:
                is_protected = True
                break
        
        if is_protected:
            protected[section_name] = section_content
        else:
            compressible[section_name] = section_content
    
    return protected, compressible

def identify_compression_candidates(compressible_sections):
    """Identify entries that are candidates for compression."""
    acceptable_token_count = 8000
    current_tokens = count_tokens("\n\n".join(compressible_sections.values()))
    
    # If under threshold, no compression needed
    if current_tokens <= acceptable_token_count:
        return {}
    
    candidates = {}
    
    # Process each compressible section
    for section_name, content in compressible_sections.items():
        section_candidates = []
        
        # Split into entries by date patterns
        entries = re.split(r'(?=^\*\*20\d{2})', content, flags=re.MULTILINE)
        
        for entry in entries:
            if not entry.strip():
                continue
            
            entry_tokens = count_tokens(entry)
            
            # Check age by looking for date patterns
            date_match = re.search(r'\*\*(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?', entry)
            if date_match:
                year = int(date_match.group(1))
                month = int(date_match.group(2)) if date_match.group(2) else 1
                day = int(date_match.group(3)) if date_match.group(3) else 1
                
                entry_date = datetime(year, month, day)
                age_months = (datetime.now() - entry_date).days / 30
                
                # Classification logic
                if age_months > 12 and entry_tokens > 50:  # >1 year old, verbose
                    action = 'ARCHIVE'
                    reason = f'>{int(age_months)} months old, verbose entry'
                elif age_months > 6 and entry_tokens > 30:  # >6 months, somewhat verbose
                    action = 'COMPRESS'
                    reason = f'>{int(age_months)} months old'
                else:
                    action = 'KEEP'
                    reason = 'recent or concise'
            else:
                action = 'KEEP'
                reason = 'no date found'
            
            section_candidates.append({
                'original': entry,
                'action': action,
                'reason': reason,
                'tokens': entry_tokens,
                'age_months': age_months if 'age_months' in locals() else 0
            })
        
        if section_candidates:
            candidates[section_name] = section_candidates
    
    return candidates

def compress_entries(candidates):
    """Generate compressed versions of entries."""
    compressed = {}
    
    for section_name, entries in candidates.items():
        compressed_section = []
        
        for entry in entries:
            if entry['action'] == 'KEEP':
                compressed_section.append(entry['original'])
            elif entry['action'] == 'COMPRESS':
                # Simple compression: reduce date precision, shorten verbose text
                compressed_text = compress_entry_text(entry['original'])
                compressed[section_name] = compressed.get(section_name, []) + [{
                    'original': entry['original'],
                    'compressed': compressed_text,
                    'action': entry['action'],
                    'reason': entry['reason']
                }]
                compressed_section.append(compressed_text)
            elif entry['action'] == 'ARCHIVE':
                # Keep minimal summary, archive full details
                summary_text = create_summary(entry['original'])
                compressed[section_name] = compressed.get(section_name, []) + [{
                    'original': entry['original'],
                    'compressed': summary_text,
                    'action': entry['action'],
                    'reason': entry['reason']
                }]
                compressed_section.append(summary_text)
        
        compressed[f"{section_name}_compressed"] = '\n\n'.join(compressed_section)
    
    return compressed

def compress_entry_text(text):
    """Compress a single entry's text."""
    # Compress date format (YYYY-MM-DD → YYYY-MM)
    text = re.sub(r'\*\*(\d{4})-(\d{2})-\d{2}\*\*', r'**\1-\2:**', text)
    
    # Remove overly verbose phrases while keeping key information
    text = re.sub(r'\busing.*?(?:scripts?|tools?|methods?)\b,? ', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bimplemented.*?(?:via|with|using)\b.*?[,;.]', '.', text, flags=re.IGNORECASE)
    
    # Truncate if still too long (rough token estimate)
    if count_tokens(text) > 100:
        # Keep first sentence + key outcomes
        sentences = re.split(r'[.!?]', text)
        compressed = sentences[0] + '.'
        if len(sentences) > 1 and any(word in ' '.join(sentences[1:]).lower() for word in ['result', 'outcome', 'completed', 'finished']):
            compressed += ' ' + sentences[1] + '.'
        text = compressed
    
    return text

def create_summary(text):
    """Create a minimal 1-liner summary for archived entries."""
    # Extract date
    date_match = re.search(r'\*\*(\d{4}(?:-\d{2})?(?:-\d{2})?)\*\*', text)
    date = date_match.group(1) if date_match else 'UNKNOWN'
    
    # Extract key action words
    actions = ['shipped', 'implemented', 'completed', 'created', 'achieved', 'started', 'finished']
    for action in actions:
        if action in text.lower():
            # Get next ~20 words after the action
            action_index = text.lower().find(action)
            following_text = text[action_index:action_index+100]
            # Clean up and create summary
            summary = re.sub(r'^.*?'+action, action.title(), following_text, flags=re.IGNORECASE)
            summary = re.sub(r'[.!?].*', '.', summary)
            return f'**{date}:** {summary}'
    
    # Fallback: just truncate
    return f'**{date}:** {text[:100]}...'

def generate_archive_content(compressed):
    """Generate content for memory/.memory-archive.md."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    archive_lines = [
        "# MEMORY.md Archive",
        "",
        f"Generated: {today_str}",
        "",
        f"## {today_str} Compression",
        "",
        "Full details of compressed/archived MEMORY.md entries.",
        ""
    ]
    
    has_entries = False
    
    for key, items in compressed.items():
        if not key.endswith('_compressed') and isinstance(items, list):
            section_name = key.replace('_', ' ').title()
            archive_lines.append(f"### {section_name}")
            archive_lines.append("")
            
            for item in items:
                if item['action'] in ['COMPRESS', 'ARCHIVE']:
                    archive_lines.append(f"Original entry ({item['action']} - {item['reason']}):")
                    archive_lines.append("```"                    archive_lines.append(item['original'])
                    archive_lines.append("```")
                    archive_lines.append("")
                    archive_lines.append(f"Compressed to: {item['compressed']}")
                    archive_lines.append("")
                    has_entries = True
    
    if not has_entries:
        archive_lines.append("No entries archived in this compression run.")
    
    return '\n'.join(archive_lines)

def generate_compression_report(original_content, compressed_data, dry_run=False):
    """Generate the compression report for human review."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    report_path = f'memory/sandman/{today_str}-memory_compression.md'
    
    original_tokens = count_tokens(original_content)
    
    # Estimate compressed size
    compressed_sections = [v for k, v in compressed_data.items() if k.endswith('_compressed')]
    estimated_compressed_tokens = sum(count_tokens(section) for section in compressed_sections) if compressed_sections else original_tokens
    
    # Get stats from archived items
    archived_count = sum(1 for items in compressed_data.values() 
                        if isinstance(items, list) 
                        for item in items if item.get('action') == 'ARCHIVE')
    compressed_count = sum(1 for items in compressed_data.values() 
                          if isinstance(items, list) 
                          for item in items if item.get('action') == 'COMPRESS')
    protected_sections = sum(1 for k, v in compressed_data.items() 
                            if isinstance(v, str) and not k.endswith('_compressed'))
    
    report_lines = [
        "# MEMORY.md Compression Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Compression Summary",
        "",
        f"- **Current size:** {original_tokens:,} tokens",
        f"- **Estimated compressed size:** {estimated_compressed_tokens:,} tokens",
        f"- **Compression ratio:** {((original_tokens - estimated_compressed_tokens) / max(original_tokens, 1) * 100):.1f}% reduction",
        f"- **Protected sections:** ~{protected_sections} (untouched)",
        f"- **Entries compressed:** {compressed_count}",
        f"- **Entries archived:** {archived_count}",
        "",
        "## Proposed Changes",
        ""
    ]
    
    # Show diff-style changes
    for key, items in compressed_data.items():
        if isinstance(items, list) and items:
            section_name = key.replace('_', ' ').title()
            report_lines.append(f"### {section_name}")
            report_lines.append("")
            
            for item in items:
                if item['action'] in ['COMPRESS', 'ARCHIVE']:
                    report_lines.append("```diff")
                    report_lines.append(f"- {item['original'].strip()}")
                    report_lines.append(f"+ {item['compressed'].strip()}")
                    report_lines.append("```")
                    report_lines.append("")
                    report_lines.append(f"**Action:** {item['action']} - {item['reason']}")
                    report_lines.append("")
    
    report_lines.extend([
        "## Application Instructions",
        "",
        "1. **Review archive file** created at memory/.memory-archive.md",
        "2. **Verify archived details** preserve full original information",
        "3. **Apply compressed versions** to MEMORY.md manually",
        "4. **Check token count** in updated MEMORY.md (target: 6,000-8,000)",
        "5. **Commit changes** with message: \"MEMORY.md compression (Sandman {today_str})\"",
        "6. **Delete this report** after successful application",
        "",
        "**Critical:** Only apply after confirming archive integrity.",
        "**Protected sections** (Identity, Core Patterns) are never touched.",
        ""
    ])
    
    content = '\n'.join(report_lines)
    
    if dry_run:
        print("DRY RUN MODE:")
        print(content[:2000] + "..." if len(content) > 2000 else content)
        print(f"Would write report to: {report_path}")
        print(f"Would update archive: memory/.memory-archive.md")
    else:
        try:
            # Write report
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Compression report written to: {report_path}")
            
            # Write archive (append mode if exists)
            archive_path = Path('/home/deva/shared/memory/.memory-archive.md')
            archive_content = generate_archive_content(compressed_data)
            
            mode = 'a' if archive_path.exists() else 'w'
            with open(archive_path, mode, encoding='utf-8') as f:
                if mode == 'a':
                    f.write('\n\n' + '='*50 + '\n\n')
                f.write(archive_content)
            print(f"Archive updated: {archive_path}")
            
        except Exception as e:
            print(f"Error writing files: {e}", file=sys.stderr)
            return False
    
    return True

def main():
    parser = argparse.ArgumentParser(description="Compress MEMORY.md content")
    parser.add_argument('--dry-run', action='store_true', help="Test mode - don't modify files")
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("Running in DRY RUN mode")
    
    # Read current MEMORY.md
    content = read_memory_file()
    if not content:
        return 1
    
    # Parse into sections
    sections = parse_memory_sections(content)
    
    # Identify protected vs compressible
    protected, compressible = identify_protected_sections(sections)
    
    if args.dry_run:
        print(f"Found {len(protected)} protected sections, {len(compressible)} compressible")
    
    # Identify compression candidates
    candidates = identify_compression_candidates(compressible)
    
    if not candidates:
        print("No compression needed - under token threshold")
        # Still write a report
        today_str = datetime.now().strftime('%Y-%m-%d')
        report_path = f'memory/sandman/{today_str}-memory_compression.md'
        content = f"""# MEMORY.md Compression Report

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

No compression needed. Current token count is within acceptable limits.
"""
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Report written to: {report_path}")
        return 0
    
    # Generate compressed versions
    compressed_data = compress_entries(candidates)
    
    # Generate report and archive
    success = generate_compression_report(content, compressed_data, args.dry_run)
    
    return 0 if success else 1

if __name__ == '__main__':
    sys.exit(main())