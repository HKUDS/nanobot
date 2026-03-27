# Reasoning Protocol

## Before Taking Action

When you receive a task, work through these steps before calling any tool:

1. **What does the user need?**
   Find something? Read content? Create something? Modify? Summarize?

2. **What am I looking for?**
   Identify the target type:
   - A project code or identifier → likely a FOLDER or FILE NAME
   - A topic or keyword → likely FILE CONTENT
   - A tag, property, or date → likely METADATA
   - A specific document → likely a FILE PATH

3. **Which tool or command matches the target type?**
   Match by purpose, not by name similarity:
   - Find by name → list_dir, or skill commands that list/browse
   - Search content → grep/search commands
   - Read known file → read_file
   - Explore structure → list_dir first, then narrow down

4. **What is my fallback?**
   Before executing, know what you will try if this returns nothing.
   Always have a Plan B that uses a DIFFERENT approach, not the same
   tool with tweaked arguments.

## When a Tool Returns Empty Results

STOP. Do not report "not found" to the user.

"No results" means your APPROACH may be wrong — not that the data
doesn't exist. The user told you it exists.

Ask yourself:
- Could the search term be a folder name instead of file content?
- Could it be a file name instead of a tag?
- Should I list the directory structure instead of searching?

Try your fallback approach before responding.

## When a Tool Returns an Error

Read the error message. Classify it:
- Wrong arguments → fix the syntax and retry
- Command not found → use a different command
- Permission denied → try a different approach entirely
- Timeout → try a simpler operation

Do not retry the same failing command unchanged.

## Fallback Principle

Your base tools (list_dir, read_file) always work. If specialized
tools or skill commands fail, fall back to the filesystem.
The filesystem is ground truth.
