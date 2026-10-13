import type { TuiCommand } from "../menus/command-menu"

export const LOCAL_COMMANDS: TuiCommand[] = [
  {
    command: "/sessions",
    title: "Sessions",
    description: "Find and switch conversations",
    action: "sessions",
  },
  {
    command: "/new-chat",
    title: "New saved chat",
    description: "Keep this conversation and start another",
    action: "new-chat",
  },
  {
    command: "/context",
    title: "Agent context",
    description: "Explain what this session contributes to the next prompt",
    action: "context",
  },
  {
    command: "/usage",
    title: "Token usage",
    description: "Show context occupancy and recent model-call input tokens",
    action: "usage",
  },
  {
    command: "/diff",
    title: "Last turn diff",
    description: "Inspect file changes from the latest turn",
    action: "diff",
  },
  {
    command: "/branch",
    title: "Branch from reply",
    description: "Continue from an earlier completed reply",
    action: "branch",
  },
  {
    command: "/detach",
    title: "Detach",
    description: "Close this terminal UI and keep the agent running",
    action: "detach",
  },
  {
    command: "/exit",
    title: "Exit",
    description: "Close this terminal UI",
    action: "exit",
  },
]
