# arXiv API Reference

## API Endpoint

Base URL: `http://export.arxiv.org/api/query`

## Query Parameters

- `search_query`: Search query using arXiv query syntax
- `start`: Starting index (0-based)
- `max_results`: Maximum number of results (default: 10, max: 2000)
- `sortBy`: Sort field (`relevance`, `lastUpdatedDate`, `submittedDate`)
- `sortOrder`: `ascending` or `descending`
- `submittedDate`: Date range filter (format: `YYYYMMDDHHMMSS*YYYYMMDDHHMMSS`)

## Query Syntax

### Field Queries

- `all:term` - Search in all fields
- `ti:term` - Title
- `au:term` - Author
- `abs:term` - Abstract
- `cat:term` - Category
- `co:term` - Comment

### Boolean Operators

- `AND` - Both conditions must match
- `OR` - Either condition matches
- `ANDNOT` - First matches, second doesn't

### Category Codes

- `cs.AI` - Artificial Intelligence
- `cs.CV` - Computer Vision and Pattern Recognition
- `cs.HC` - Human-Computer Interaction
- `cs.LG` - Machine Learning
- `cs.RO` - Robotics

## Example Queries

```
# Vision-language-action papers
all:"vision language action" AND (cat:cs.AI OR cat:cs.CV OR cat:cs.RO)

# Robotic manipulation
all:"robotic manipulation" AND cat:cs.RO

# Recent papers (last 7 days)
all:"VLA" AND submittedDate:[20250101*20250108]
```

## Response Format

Returns Atom XML with entries containing:
- `<id>` - arXiv ID
- `<title>` - Paper title
- `<author>` - Author names
- `<summary>` - Abstract
- `<published>` - Publication date
- `<category>` - Subject categories
- `<link>` - PDF and abstract URLs

## Rate Limits

- No authentication required
- Rate limit: ~1 request per 3 seconds recommended
- Max results per query: 2000

## References

- [arXiv API User Manual](https://arxiv.org/help/api/user-manual)
- [arXiv Query Syntax](https://arxiv.org/help/api/user-manual#query_details)
