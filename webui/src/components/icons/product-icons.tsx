import { forwardRef, type ReactNode } from "react";
import type { LucideIcon, LucideProps } from "lucide-react";

function productIcon(name: string, drawing: ReactNode): LucideIcon {
  const Icon = forwardRef<SVGSVGElement, LucideProps>(({ size = 24, color = "currentColor", strokeWidth = 1.75, absoluteStrokeWidth, className, children, ...props }, ref) => (
    <svg ref={ref} xmlns="http://www.w3.org/2000/svg" width={size} height={size}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round"
      vectorEffect={absoluteStrokeWidth ? "non-scaling-stroke" : undefined}
      aria-hidden="true" className={className} data-product-icon={name} {...props}>
      {drawing}{children}
    </svg>
  ));
  Icon.displayName = name;
  return Icon;
}

export const NewChatIcon = productIcon("new-chat", <><path d="M11 20H7l-4 2V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v4" /><path d="M17 14v7m-3.5-3.5h7" /></>);
export const ComposeIcon = productIcon("compose", <g transform="scale(1.5)" fill="currentColor" stroke="none"><path fillRule="evenodd" clipRule="evenodd" d="M7.25 1C7.66414 1 7.99988 1.33589 8 1.75C8 2.16421 7.66421 2.5 7.25 2.5H4.75C3.50745 2.5 2.50012 3.50744 2.5 4.75V11.25C2.5 12.4926 3.50736 13.5 4.75 13.5H11.25C12.4926 13.5 13.5 12.4926 13.5 11.25V8.75C13.5001 8.33589 13.8359 8 14.25 8C14.6641 8 14.9999 8.33589 15 8.75V11.25C15 13.3211 13.3211 15 11.25 15H4.75C2.67893 15 1 13.3211 1 11.25V4.75C1.00012 2.67905 2.67899 1 4.75 1H7.25Z" /><path fillRule="evenodd" clipRule="evenodd" d="M13.4326 1.26953C13.7913 0.910937 14.3728 0.910883 14.7314 1.26953C15.0897 1.6282 15.0899 2.20981 14.7314 2.56836L9.2373 8.06152C8.68101 8.6177 7.94043 8.95161 7.15527 9C7.06754 9.0052 6.99468 8.93248 7 8.84473C7.04847 8.05961 7.38232 7.31897 7.93848 6.7627L13.4326 1.26953Z" /></g>);
export const ConversationIcon = productIcon("conversation", <><path d="M7 4h10a4 4 0 0 1 4 4v7a4 4 0 0 1-4 4H8l-5 3V8a4 4 0 0 1 4-4Z" /><path d="M7 9h10M7 13h6" /></>);
export const SearchIcon = productIcon("search", <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></>);
export const AppsIcon = productIcon("apps", <><rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1.75" /><rect x="14" y="3.5" width="6.5" height="6.5" rx="1.75" /><rect x="3.5" y="14" width="6.5" height="6.5" rx="1.75" /><rect x="14" y="14" width="6.5" height="6.5" rx="1.75" /></>);
export const SkillsIcon = productIcon("skills", <><path d="M5 18V6a3 3 0 0 1 3-3h11v14M5 18a3 3 0 0 1 3-3h11v6H8a3 3 0 0 1-3-3Z" /><path d="m9 7 2 2-2 2m5-4h2m-5 11h5" /></>);
export const AutomationsIcon = productIcon("automations", <><rect x="3" y="5" width="18" height="16" rx="3" /><path d="M7 3v4m10-4v4M3 10h18m-8 2-4 4h4l-2 4 5-5h-4l1-3Z" /></>);
export const ChannelsIcon = productIcon("channels", <><path d="M4 4h9a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H8l-4 3V6a2 2 0 0 1 0-2Z" /><path d="M15 8h3a3 3 0 0 1 3 3v6a2 2 0 0 1-2 2h-3l-3 2v-4" /><path d="M7 8h5" /></>);
export const ArchiveIcon = productIcon("archive", <><rect x="3" y="3.5" width="18" height="4.5" rx="1.5" /><path d="M4.5 8v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8M9 12h6" /></>);
export const SettingsIcon = productIcon("settings", <><path d="M10 3h4l.6 2.4 2.1 1.2 2.4-.7 2 3.5-1.8 1.7v2.4l1.8 1.7-2 3.5-2.4-.7-2.1 1.2L14 21h-4l-.6-2.4-2.1-1.2-2.4.7-2-3.5 1.8-1.7v-2.4L2.9 9.4l2-3.5 2.4.7 2.1-1.2L10 3Z" /><circle cx="12" cy="12" r="3" /></>);
export const OverviewIcon = productIcon("overview", <><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M3 9h18M9 9v12m4-4v-3m4 3v-5" /><path d="M6 6h.01" /></>);
export const AppearanceIcon = productIcon("appearance", <><path d="M12 3a9 9 0 0 0 0 18h1a2 2 0 0 0 1.3-3.5 1.7 1.7 0 0 1 1.2-3H18a3 3 0 0 0 3-3A9 9 0 0 0 12 3Z" /><circle cx="7.5" cy="10" r=".8" /><circle cx="11" cy="6.8" r=".8" /><circle cx="16" cy="8" r=".8" /></>);
export const ModelsIcon = productIcon("models", <><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5" /></>);
export const CapabilitiesIcon = productIcon("capabilities", <><path d="m12 8 4 4-4 4-4-4 4-4Zm0-5v5m0 8v5M3 12h5m8 0h5" /><path d="M7 3H5a2 2 0 0 0-2 2v2m14-4h2a2 2 0 0 1 2 2v2M3 17v2a2 2 0 0 0 2 2h2m10 0h2a2 2 0 0 0 2-2v-2" /></>);
export const SystemIcon = productIcon("system", <><rect x="3" y="3" width="18" height="7" rx="2" /><rect x="3" y="14" width="18" height="7" rx="2" /><path d="M7 6.5h.01m0 11h.01M12 6.5h5m-5 11h5" /></>);
export const AdvancedIcon = productIcon("advanced", <><path d="M3 6h5m4 0h9M3 12h11m4 0h3M3 18h2m4 0h12" /><circle cx="10" cy="6" r="2" /><circle cx="16" cy="12" r="2" /><circle cx="7" cy="18" r="2" /></>);
export const AboutIcon = productIcon("about", <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10h.01" /></>);
export const AttachIcon = productIcon("attach", <path d="M8.5 12.5 14 7a2.75 2.75 0 0 1 3.89 3.89l-7.43 7.43a4.25 4.25 0 0 1-6.01-6.01l7.43-7.43a5.75 5.75 0 0 1 8.13 8.13L12.5 20.5" />);
export const SendIcon = productIcon("send", <><path d="m4 5 17 7-17 7 3-7-3-7Z" /><path d="M7 12h14" /></>);
export const VoiceIcon = productIcon("voice", <><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M6 11v1a6 6 0 0 0 12 0v-1M12 18v3m-3 0h6" /></>);
export const StopIcon = productIcon("stop", <rect x="5" y="5" width="14" height="14" rx="2.5" />);
export const RestrictedAccessIcon = productIcon("restricted-access", <><rect x="5" y="10" width="14" height="11" rx="2.5" /><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2" /></>);
export const FullAccessIcon = productIcon("full-access", <><rect x="5" y="10" width="14" height="11" rx="2.5" /><path d="M8 10V7a4 4 0 0 1 7.5-2M9 16h6m-2.5-2.5L15 16l-2.5 2.5" /></>);
export const WorkspaceIcon = productIcon("workspace", <><path d="M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" /><path d="M8 13h8m-8 4h5" /></>);
export const PromptNavigationIcon = productIcon("prompt-navigation", <><path d="M5 5v14m4-14h11M9 12h11M9 19h7" /><circle cx="5" cy="5" r="1.5" fill="currentColor" stroke="none" /><circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none" /><circle cx="5" cy="19" r="1.5" fill="currentColor" stroke="none" /></>);
export const TemporaryChatIcon = productIcon("temporary-chat", <><path d="M7 4h10a4 4 0 0 1 4 4v7a4 4 0 0 1-4 4H8l-5 3V8a4 4 0 0 1 4-4Z" strokeDasharray="3 3" /><path d="M8 10h8m-8 4h4" /></>);
export const GoalIcon = productIcon("goal", <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1.25" fill="currentColor" stroke="none" /></>);
export const DelegationIcon = productIcon("delegation", <><rect x="8" y="3" width="8" height="5" rx="1.5" /><rect x="2" y="16" width="8" height="5" rx="1.5" /><rect x="14" y="16" width="8" height="5" rx="1.5" /><path d="M12 8v4M6 16v-4h12v4" /></>);
export const TaskInspectIcon = productIcon("task-inspect", <><rect x="3" y="3" width="13" height="18" rx="2" /><path d="M7 7h5M7 11h3" /><circle cx="16" cy="15" r="4" /><path d="m19 18 3 3" /></>);
export const TaskMessageIcon = productIcon("task-message", <><path d="M12 19H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v4M7 8h10M7 12h4" /><path d="M14 17h7m-3-3 3 3-3 3" /></>);
export const QueuedTaskIcon = productIcon("task-queued", <><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5l3 2" /></>);
export const RunningTaskIcon = productIcon("task-running", <><path d="M12 3a9 9 0 1 1-9 9" /><path d="M3 7v.01M6 4v.01" /></>);
export const StoppingTaskIcon = productIcon("task-stopping", <><path d="M12 3a9 9 0 1 1-9 9M3 7v.01M6 4v.01" /><rect x="9" y="9" width="6" height="6" rx="1" /></>);
export const CompletedTaskIcon = productIcon("task-completed", <><circle cx="12" cy="12" r="9" /><path d="m7.5 12 3 3 6-6" /></>);
export const CancelledTaskIcon = productIcon("task-cancelled", <><circle cx="12" cy="12" r="9" /><path d="m9 9 6 6m0-6-6 6" /></>);
export const IncompleteTaskIcon = productIcon("task-incomplete", <><path d="M12 3a9 9 0 0 1 9 9M12 21a9 9 0 0 1-9-9" /><path d="M3 8v.01M6 5v.01M8 3v.01M21 16v.01M18 19v.01M16 21v.01" /><path d="M12 8v4" /></>);
export const InterruptedTaskIcon = productIcon("task-interrupted", <><circle cx="12" cy="12" r="9" /><path d="M9 8v8m6-8v8" /></>);
export const ErrorTaskIcon = productIcon("task-error", <><circle cx="12" cy="12" r="9" /><path d="M12 7v6m0 4h.01" /></>);
export const ActivityIcon = productIcon("activity", <><circle cx="4" cy="10" r="2" /><circle cx="12" cy="10" r="2" /><circle cx="20" cy="10" r="2" /><path d="M6 10h4m4 0h4M3 17h3m4 0h4m4 0h3" /></>);
export const StatusIcon = productIcon("status", <><path d="M3 15a9 9 0 1 1 18 0M6 20h12m-6-5 4-5" /><circle cx="12" cy="15" r="1.5" /></>);
export const CompactIcon = productIcon("compact", <><path d="M7 10h10M7 14h10M12 2v5m-2-2 2 2 2-2M12 22v-5m-2 2 2-2 2 2" /></>);
export const ResumeIcon = productIcon("resume", <><path d="m9 5 11 7-11 7V5Z" /><path d="M4 6v12" /></>);
export const RestartIcon = productIcon("restart", <><path d="M20 8a8.5 8.5 0 1 0 0 8M20 3v5h-5" /></>);
export const UpdateIcon = productIcon("update", <><path d="M12 15V3m-4 4 4-4 4 4M4 13v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6" /></>);
export const ImportIcon = productIcon("import", <><path d="M10 4h7l4 4v11a2 2 0 0 1-2 2h-9M17 4v5h4M3 13h11m-4-4 4 4-4 4" /></>);
export const AppActionsIcon = productIcon("app-actions", <><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M3 8h18M7 5.5h.01M8 14h.01M12 14h.01M16 14h.01" /></>);
export const McpIcon = productIcon("mcp", <><path d="M8 3v5m8-5v5M5 8h14v3a7 7 0 0 1-14 0V8Zm7 10v3" /></>);
export const ToolRunIcon = productIcon("tool-run", <path d="M14 4a6 6 0 0 0-7 7L3.5 18a2 2 0 0 0 2.5 2.5l7-3.5a6 6 0 0 0 7-7l-4 4-5-1-1-5 4-4Z" />);
export const FileReadIcon = productIcon("file-read", <><path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10l-7-7Zm0 0v7h7M8 14h8m-8 3h5" /></>);
export const FileListIcon = productIcon("file-list", <><path d="M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11H3V6Z" /><path d="M7 12h.01M10 12h7M7 16h.01M10 16h5" /></>);
export const MemoryIcon = productIcon("memory", <><rect x="5" y="3" width="15" height="18" rx="2" /><path d="M5 8H3m2 5H3m2 5H3M14 3v8l2-1.5 2 1.5V3M9 15h7m-7 3h4" /></>);
export const DreamIcon = productIcon("dream", <><path d="M14 4A8.5 8.5 0 1 0 20 15a8 8 0 0 1-6-11Z" /><path d="m18 3 1 3 3 1-3 1-1 3-1-3-3-1 3-1 1-3Z" /></>);
export const DreamLogIcon = productIcon("dream-log", <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 7h8m-8 5h8m-8 5h5" /></>);
export const RestoreMemoryIcon = productIcon("restore-memory", <><path d="M13 4h5a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-4M4 4v5h5M4 9a6 6 0 1 1 3 5" /></>);
export const PromptTemplateIcon = productIcon("prompt-template", <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="m10 8-3 4 3 4m4-8 3 4-3 4" /></>);
export const TriggerIcon = productIcon("trigger", <path d="m13 2-9 12h7l-1 8 10-13h-7l0-7Z" />);
export const PairingIcon = productIcon("pairing", <><path d="m9 15-2 2a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m4 2 2-2a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0M8 16l8-8" /></>);
export const HelpIcon = productIcon("help", <><circle cx="12" cy="12" r="9" /><path d="M9 8a3 3 0 0 1 6 0c0 2-3 2-3 5m0 4h.01" /></>);
export const HistoryIcon = productIcon("history", <><path d="M4 9a8.5 8.5 0 1 1 0 7M4 4v5h5M12 7v5l3 2" /></>);
export const WebSearchIcon = productIcon("web-search", <><circle cx="10" cy="10" r="7" /><path d="M3 10h14M10 3a12 12 0 0 0 0 14 12 12 0 0 0 0-14" /><circle cx="17" cy="17" r="4" /><path d="m20 20 2 2" /></>);
export const ImageGenerationIcon = productIcon("image-generation", <><path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5M4 16l5-5 8 9" /><circle cx="9" cy="8" r="1" /><path d="m18 2 1 4 3 1-3 1-1 4-1-4-3-1 3-1 1-4Z" /></>);
export const EditIcon = productIcon("edit", <><path d="m15 4 5 5M4 15l11-11a2 2 0 0 1 3 0l2 2a2 2 0 0 1 0 3L9 20l-6 1 1-6Z" /></>);
export const ProviderIcon = productIcon("provider", <><path d="M7 3h10l5 9-5 9H7L2 12l5-9Z" /><path d="M8 8h8v8H8V8Z" /></>);
