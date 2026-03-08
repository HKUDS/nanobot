#!/usr/bin/env python3
"""
Startup Sequence Verification Script

Verifies that the AGENTS.md startup sequence was followed correctly.
Checks for evidence that all required steps were completed.

Exit codes:
  0 - All steps verified successfully
  1 - One or more required steps were skipped
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime, timedelta

# ANSI color codes for loud failures
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BOLD = '\033[1m'
RESET = '\033[0m'

WORKSPACE = Path(__file__).parent.parent
STATE_FILE = WORKSPACE / '.startup-state.json'

REQUIRED_STEPS = {
    'load_context_executed': 'load-context.py was run',
    'sessions_checked': 'Pending sessions were checked',
    'soul_loaded': 'SOUL.md was loaded',
    'user_loaded': 'USER.md was loaded',
    'memory_loaded': 'MEMORY.md was loaded',
    'diary_loaded': 'Diary context was loaded'
}


def print_error(message):
    """Print error message in red with visual emphasis"""
    print(f"\n{RED}{BOLD}{'=' * 70}{RESET}")
    print(f"{RED}{BOLD}🚨 STARTUP SEQUENCE VIOLATION 🚨{RESET}")
    print(f"{RED}{BOLD}{'=' * 70}{RESET}")
    print(f"{RED}{message}{RESET}")
    print(f"{RED}{BOLD}{'=' * 70}{RESET}\n")


def print_success(message):
    """Print success message in green"""
    print(f"{GREEN}✓ {message}{RESET}")


def print_warning(message):
    """Print warning message in yellow"""
    print(f"{YELLOW}⚠ {message}{RESET}")


def verify_startup_sequence():
    """
    Verify all required startup steps were completed.
    Returns True if all verified, False otherwise.
    """
    
    # Check if state file exists
    if not STATE_FILE.exists():
        print_error(
            "No startup state file found!\n\n"
            "The startup sequence has not been initialized.\n"
            "You MUST run the startup sequence from AGENTS.md before greeting.\n\n"
            f"Expected state file: {STATE_FILE}"
        )
        return False
    
    # Load state file
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
    except json.JSONDecodeError as e:
        print_error(
            f"Corrupted startup state file!\n\n"
            f"Error: {e}\n\n"
            f"File: {STATE_FILE}"
        )
        return False
    
    # Check timestamp - state should be from this session (within last 5 minutes)
    if 'timestamp' in state:
        try:
            state_time = datetime.fromisoformat(state['timestamp'])
            now = datetime.now()
            age = now - state_time
            
            if age > timedelta(minutes=5):
                print_warning(
                    f"Startup state is {age.seconds // 60} minutes old.\n"
                    "This may be from a previous session."
                )
        except (ValueError, TypeError):
            print_warning("Could not parse state timestamp")
    
    # Verify each required step
    missing_steps = []
    for step_key, step_description in REQUIRED_STEPS.items():
        if not state.get(step_key, False):
            missing_steps.append(step_description)
        else:
            print_success(step_description)
    
    # If any steps are missing, fail loudly
    if missing_steps:
        print_error(
            "REQUIRED STARTUP STEPS WERE SKIPPED!\n\n"
            "Missing steps:\n" +
            "\n".join(f"  ❌ {step}" for step in missing_steps) +
            "\n\n"
            "You MUST complete ALL startup steps from AGENTS.md before greeting.\n"
            "DO NOT SKIP STEPS. DO NOT TAKE SHORTCUTS.\n\n"
            "Go back and run the complete startup sequence."
        )
        return False
    
    # All checks passed
    print(f"\n{GREEN}{BOLD}✓ All startup steps verified successfully!{RESET}\n")
    return True


def main():
    """Main entry point"""
    if not verify_startup_sequence():
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
