---
name: long-form-writer
description: Generate comprehensive long-form articles and reports with structured workflow. Use when needing to create in-depth tutorials, research reports, or analysis documents exceeding 2000 words. Supports multi-layer expansion, case enrichment, and multiple output formats.
---

# Long Form Writer

Generate comprehensive long-form articles and reports with structured depth.

## When to Use This Skill

- Create tutorials exceeding 2000 words
- Write research reports with multiple sections
- Generate analysis documents with case studies
- Transform raw data into structured narratives
- Expand outline into full content

## Core Workflow (4 Layers)

### L1: Structure (大纲规划)

Define the article architecture:

```markdown
## Article Blueprint

**Type**: [tutorial | report | analysis | guide]
**Target Length**: [3000 | 5000 | 8000 | 10000] words
**Audience**: [technical | general | executive]

### Chapter Plan
1. [Title] - [Word count] - [Key points]
2. [Title] - [Word count] - [Key points]
...
```

### L2: Expand (章节展开)

Generate each chapter independently:

```
For each chapter:
1. Write 500-1500 words
2. Include: concept + example + application
3. Add subsections if needed (recursive)
4. Mark [EXPAND] for sections needing more depth
```

### L3: Enrich (素材增强)

Add supporting materials:

- **Cases**: Real user examples from chat history
- **Data**: Statistics, comparisons, trends
- **Visuals**: Screenshot suggestions, diagram descriptions
- **FAQ**: Common questions and answers

### L4: Polish (润色检查)

Apply quality standards:

- [ ] Remove AI filler phrases
- [ ] Check for 3-part structures → convert to 2 or 4
- [ ] Vary sentence length
- [ ] Add personal insights
- [ ] Verify logical flow between chapters

## Usage Patterns

### Pattern 1: From Data to Report

```bash
# Input: analysis.json
# Output: comprehensive report

long-form-writer generate \
  --input data.json \
  --type report \
  --template structured \
  --output report.md
```

### Pattern 2: From Outline to Article

```bash
# Input: outline.md
# Output: full tutorial

long-form-writer expand \
  --outline outline.md \
  --depth 3 \
  --word-count 5000 \
  --output article.md
```

### Pattern 3: Chat History to Guide

```bash
# Extract cases from chat, generate guide

long-form-writer guide \
  --chat-history chat.json \
  --topic "OpenClaw Usage" \
  --output guide.md
```

## Integration with Other Skills

| Skill | Usage |
|-------|-------|
| feishu-chat-extractor | Extract real cases from group chats |
| summarize | Compress reference materials |
| nano-pdf | Export final PDF |

## Output Formats

- **Markdown** (default): Editable, version control friendly
- **PDF**: Professional delivery
- **Feishu Doc**: Collaborative editing

## Quality Checklist

Before delivery, verify:

1. [ ] Each chapter has concrete examples
2. [ ] Total word count meets target
3. [ ] No section is purely theoretical
4. [ ] Data/sources are cited
5. [ ] Conclusion ties back to introduction
6. [ ] Formatting is consistent

## Examples

See `references/examples.md` for sample outputs.