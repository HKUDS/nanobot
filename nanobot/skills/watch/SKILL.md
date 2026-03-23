---
name: watch
description: Monitor URLs, files, or conditions and notify when changes occur
always: false
---

# Watch / Monitor Skill

When a user asks you to **watch**, **monitor**, or **notify** them about something, follow this pattern:

## Step 1: Identify What to Watch
Parse the user's request for:
- **Target**: URL, file path, API endpoint, or condition to check
- **Trigger condition**: What constitutes a notification (any change, specific threshold, keyword appears, etc.)
- **Frequency**: How often to check (default: every 5 minutes = 300 seconds)

## Step 2: Capture Baseline (if applicable)
If monitoring for changes, first fetch/read the current state to establish a baseline. Include this baseline in the cron job message so the agent can compare against it.

## Step 3: Set Up Monitoring
Use the `cron` tool to create a recurring job:

```
cron(
  action="add",
  message="Check [target]. Previous state: [baseline]. If the state has changed or the condition [trigger] is met, use the message tool to notify the user with the details of the change.",
  every_seconds=300,
  description="Monitoring [target] for [trigger condition]"
)
```

## Step 4: Confirm to User
Tell the user what you're monitoring, how often, and how they'll be notified. Remind them they can use `cron(action="list")` to see active monitors and `cron(action="remove", job_id="...")` to stop monitoring.

## Monitoring Patterns

### URL/API Monitoring
- Fetch the URL using web_fetch
- Compare response content or status with baseline
- Notify on meaningful changes (ignore timestamps, tracking params)

### File Monitoring
- Read the file content
- Compare with baseline
- Notify on content changes

### Condition Monitoring
- Evaluate the condition (e.g., stock price > threshold)
- Notify when condition becomes true

### Threshold Monitoring
- Check a metric value
- Notify when it crosses above or below a threshold

## Best Practices
- Don't create more than 10 active monitoring jobs simultaneously
- Use reasonable check intervals (5min for URLs, 30min for slow-changing data)
- Include enough context in the cron message for the agent to make good comparisons
- When the monitoring condition is met, consider whether to keep monitoring or stop
