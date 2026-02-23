# Skill: Adzuna Job Searcher

Finds real-time job listings using the Adzuna API and pings a digest to the configured Discord webhook.

## Description
This skill triggers a Python bridge that communicates with an MCP (Model Context Protocol) server. It fetches job titles, companies, locations, and estimated salaries, then formats them into a clean Discord-ready digest.

## Usage
Use this tool whenever the user asks to "find jobs," "search for work," or "check for listings" in a specific area.

### Constraints
- **Country**: Currently locked to 'us' (United States).
- **Arguments**: Requires a search query (what) and a city/zip code (where).

## Command Template
```bash
python3 search_jobs.py '{{query}}' '{{location}}'
```

## Examples
User: "Find me software engineering internships in Irvine."
Assistant: 
```bash
python3 search_jobs.py 'Software Engineering Internship' 'Irvine'
**User:** "Are there any React developer roles in Irvine?"
**Assistant:**
python3 search_jobs.py 'React Developer' 'Irvine'
```
