# 📚 nanobot Usage Examples

This document provides practical examples of using nanobot for various tasks.

## 🏠 Daily Life Assistant

### Morning Routine
```bash
# Set daily morning reminder
nanobot cron add --name "morning" --message "Good morning! Here's your daily briefing" --cron "0 8 * * *"
```

### Weather Check
```bash
nanobot agent -m "What's the weather in Tokyo today?"
nanobot agent -m "Do I need an umbrella in London?"
```

### Reminders
```bash
nanobot agent -m "Remind me to call mom at 3pm"
nanobot agent -m "Set a timer for 25 minutes"
```

## 💻 Software Development

### Code Help
```bash
# Explain code
nanobot agent -m "Explain this Python code: [paste code]"

# Debug errors
nanobot agent -m "Why am I getting this error: [error message]"

# Code review
nanobot agent -m "Review this function for bugs and improvements: [code]"
```

### Git Workflow
```bash
# Generate commit messages
nanobot agent -m "Generate a commit message for: added user authentication"

# PR descriptions
nanobot agent -m "Write a PR description for my weather skill feature"
```

## 📊 Research & Learning

### Information Gathering
```bash
nanobot agent -m "Summarize the latest AI research trends"
nanobot agent -m "What are the top 5 Python libraries for ML?"
```

### Study Assistant
```bash
nanobot agent -m "Explain quantum computing in simple terms"
nanobot agent -m "Give me practice problems for dynamic programming"
```

## 🔧 System Administration

### Using tmux Skill
```bash
nanobot agent -m "Show me all tmux sessions"
nanobot agent -m "Create a tmux session called 'dev'"
```

### File Management
```bash
nanobot agent -m "Find all Python files modified today"
nanobot agent -m "Compress this directory to a tar.gz"
```

## 🤖 Chat Channels Integration

### Telegram
```bash
# After setting up Telegram (see main README)
# Just message your bot on Telegram:
"What's the weather?"
"Set a reminder for 5pm"
"Search for Python tutorials"
```

### WhatsApp
```bash
# After linking WhatsApp
# Send voice messages - they'll be transcribed automatically
# Send text commands just like Telegram
```

## 🎯 Advanced Usage

### Multi-step Tasks
```bash
nanobot agent -m "Search for TypeScript tutorials, summarize the top 3, and create a learning plan"
```

### Background Tasks
```bash
# Using cron for scheduled analysis
nanobot cron add --name "market-check" \
  --message "Check Bitcoin price and notify if over $50k" \
  --every 3600
```

### Custom Workflows
```bash
# Morning briefing
nanobot cron add --name "briefing" \
  --message "Give me: weather in SF, top tech news, and my GitHub activity" \
  --cron "0 9 * * 1-5"
```

## 💡 Tips & Tricks

### 1. Be Specific
❌ "Help me code"
✅ "Help me write a Python function to parse JSON from a file"

### 2. Provide Context
❌ "Fix this bug"
✅ "Fix this bug in my Flask app: [error] [code] [what I've tried]"

### 3. Use Skills
✅ "Use the tmux skill to show my sessions"
✅ "Use weather skill to get forecast for next 3 days"

### 4. Chain Commands
✅ "Search for React hooks tutorial, then explain useState with an example"

## 🚀 Integration Examples

### With VSCode
```bash
# Add as a task in .vscode/tasks.json
{
  "label": "Ask nanobot",
  "type": "shell",
  "command": "nanobot agent -m '${input:question}'"
}
```

### With cURL (via Docker)
```bash
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, nanobot!"}'
```

## 🎓 Learning Path

1. **Week 1**: Basic queries, weather, reminders
2. **Week 2**: Code assistance, debugging help
3. **Week 3**: Custom skills, scheduled tasks
4. **Week 4**: Advanced integrations, workflows

## 📖 More Resources

- [Main README](../README.md)
- [Skills Documentation](../nanobot/skills/README.md)
- [Configuration Guide](../README.md#configuration)

---

💡 **Have more examples?** Open a PR to add them!


## 🌍 Real-World Scenarios

### Scenario 1: Content Creator
```bash
# Daily content ideas
nanobot agent -m "Give me 5 YouTube video ideas about Python"

# Script writing
nanobot agent -m "Write a 2-minute script about AI trends"
```

### Scenario 2: Student
```bash
# Homework help
nanobot agent -m "Explain the difference between TCP and UDP"

# Essay outline
nanobot agent -m "Create an outline for an essay on climate change"
```

### Scenario 3: Entrepreneur
```bash
# Market research
nanobot agent -m "What are the trends in SaaS for 2025?"

# Business ideas
nanobot agent -m "Validate this business idea: [your idea]"
```

## ⚠️ Common Pitfalls

### ❌ Don't Do This:
```bash
# Too vague
nanobot agent -m "Help"

# No context
nanobot agent -m "Fix it"
```

### ✅ Do This Instead:
```bash
# Specific and clear
nanobot agent -m "Help me debug this Python TypeError: [error details]"

# With full context
nanobot agent -m "Fix this authentication bug in my Express.js app: [code + error]"
```

## 🔗 Integration with Other Tools

### GitHub Actions
```yaml
# .github/workflows/nanobot.yml
name: Ask nanobot
on: [push]
jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Code review
        run: nanobot agent -m "Review the changes in this commit"
```

### Shell Alias
```bash
# Add to ~/.bashrc or ~/.zshrc
alias ask="nanobot agent -m"

# Usage
ask "What's the weather?"
```