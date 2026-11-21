import { useEffect, useState } from "react";
import { CalendarClock, ListFilter } from "lucide-react";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ComposerUsagePopover } from "@/components/thread/ComposerUsagePopover";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { Button } from "@/components/ui/button";
import type { UIMessage, WorkspaceScopePayload, WorkspacesPayload } from "@/lib/types";

const LONG_USER_MESSAGE_EN = [
  "Can you review this release checklist and the deployment log below before we cut v0.9.4?",
  "",
  "Release checklist:",
  "1. Verify WebSocket reconnection restores pending prompts and preserves turn order across idle reconnects.",
  "2. Confirm SQLite WAL compaction does not block active session reads during high-throughput tool runs.",
  "3. Check mobile Safari safe-area bottom inset when the soft keyboard opens and closes repeatedly.",
  "4. Validate custom background blur contrast on composer, side panel, and user message bubbles in both themes.",
  "5. Inspect slash command and skill palette keyboard navigation on narrow viewports.",
  "6. Ensure fallback model badges stay aligned with response metadata after streaming finishes.",
  "",
  "Recent staging deployment output:",
  "[10:12:04] gateway.startup: loaded 14 skills, 3 MCP presets, 2 active channels (websocket, telegram)",
  "[10:12:05] session.sqlite: WAL checkpoint completed in 11ms (0 busy retries, 184 sessions indexed)",
  "[10:12:08] webui.assets: serving production bundle hash 9a4f2c18 from nanobot/web/dist",
  "[10:12:14] agent.runner: turn #412 started with model preset default (context 24,180 / 200,000 tokens)",
  "[10:12:16] tools.exec: ran `pytest tests/webui/test_transcript.py` -> 28 passed in 1.42s",
  "[10:12:19] tools.exec: ran `vitest run src/tests/message-bubble.test.tsx` -> 46 passed in 0.98s",
  "[10:12:24] agent.runner: turn #412 completed in 9.8s with 0 retries and 0 fallback switches",
  "[10:12:31] health.probe: ws_roundtrip_ms=14 http_status=200 memory_rss_mb=138",
  "",
  "Open questions for the final pass:",
  "- Should we keep the existing prompt navigation shortcut on macOS and Linux unchanged?",
  "- Do any channel plugins rely on the deprecated settings schema fields?",
  "- Can we summarize the changelog highlights into three crisp bullets for the release notes?",
  "- Final line sentinel: please confirm every item above is ready to ship.",
].join("\n");

const LONG_USER_MESSAGE_ZH = [
  "帮我核对一下 v0.9.4 发布前的检查清单和预发环境日志，看看还有没有遗漏的风险点：",
  "",
  "发布检查清单：",
  "1. 确认 WebSocket 断线重连后，排队中的用户消息能恢复顺序且不会重复提交。",
  "2. 确认 SQLite WAL 写入在高频工具调用期间不会阻塞会话历史分页查询。",
  "3. 检查移动端 Safari 软键盘反复弹出/收起时，底部安全区域和输入框间距是否稳定。",
  "4. 核对自定义壁纸模式下，输入框、侧边栏和用户气泡在浅色与深色主题下的毛玻璃对比度。",
  "5. 检查窄屏下 `/` 命令面板与 `$` 技能面板的键盘上下导航与滚屏表现。",
  "6. 确认流式回复完成后，回退模型标识与时间戳在操作菜单中展示一致。",
  "",
  "预发环境部署日志：",
  "[10:12:04] gateway.startup: 已加载 14 个技能、3 个 MCP 预设、2 个活跃渠道（websocket、telegram）",
  "[10:12:05] session.sqlite: WAL 检查点耗时 11ms（0 次锁等待，已索引 184 个会话）",
  "[10:12:08] webui.assets: 已挂载生产构建产物 9a4f2c18（nanobot/web/dist）",
  "[10:12:14] agent.runner: 回合 #412 启动，当前上下文 24,180 / 200,000 tokens",
  "[10:12:16] tools.exec: 运行 pytest tests/webui/test_transcript.py -> 28 项全部通过（1.42s）",
  "[10:12:19] tools.exec: 运行 vitest run src/tests/message-bubble.test.tsx -> 46 项全部通过（0.98s）",
  "[10:12:24] agent.runner: 回合 #412 完成，总耗时 9.8s，0 次重试，0 次模型回退",
  "[10:12:31] health.probe: ws_roundtrip_ms=14 http_status=200 memory_rss_mb=138",
  "",
  "最后需要确认的事项：",
  "- macOS 与 Linux 的提示词导航快捷键是否保持不变？",
  "- 现有渠道插件是否还依赖已废弃的配置字段？",
  "- 能否把本次变更提炼为 3 条简明发布说明？",
  "- 末尾标记：请确认以上全部检查项都已就绪。",
].join("\n");

const initialScope: WorkspaceScopePayload = {
  project_path: "/projects/nanobot",
  project_name: "nanobot",
  access_mode: "full",
};

const catalog: WorkspacesPayload = {
  schema_version: 1,
  default_access_mode: "full",
  default_scope: initialScope,
  recent_projects: [{ path: "/projects/nanobot", name: "nanobot" }],
  controls: { can_change_project: true },
};

export function LongUserMessageFixture({ parameters }: { parameters: URLSearchParams }) {
  const [dark, setDark] = useState(parameters.has("dark"));
  const [scope, setScope] = useState<WorkspaceScopePayload>(initialScope);
  const zh = parameters.get("lang")?.startsWith("zh") ?? false;

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const messages: UIMessage[] = zh
    ? [
        {
          id: "short-user",
          role: "user",
          content: "先把这次发版要检查的重点发你一下。",
          createdAt: 1_700_000_000_000,
        },
        {
          id: "short-assistant",
          role: "assistant",
          content: "好的，发过来我逐条核对。",
          createdAt: 1_700_000_001_000,
        },
        {
          id: "long-user",
          role: "user",
          content: LONG_USER_MESSAGE_ZH,
          createdAt: 1_700_000_002_000,
        },
        {
          id: "long-assistant",
          role: "assistant",
          content: "已逐项核对完清单与预发日志，目前 6 项核心检查和健康探针状态均正常。\n\n**发布前建议**\n- 保持现有快捷键不变，避免影响老用户肌肉记忆。\n- 所有内置渠道已迁移到新配置结构，无废弃字段残留。\n- 发布说明已可按「交互优化 / 稳定性提升 / 移动端体验」三条整理。",
          createdAt: 1_700_000_003_000,
        },
      ]
    : [
        {
          id: "short-user",
          role: "user",
          content: "Sending over the release checklist next.",
          createdAt: 1_700_000_000_000,
        },
        {
          id: "short-assistant",
          role: "assistant",
          content: "Ready whenever you are — share the checklist and logs.",
          createdAt: 1_700_000_001_000,
        },
        {
          id: "long-user",
          role: "user",
          content: LONG_USER_MESSAGE_EN,
          createdAt: 1_700_000_002_000,
        },
        {
          id: "long-assistant",
          role: "assistant",
          content: "Everything in the staging log and checklist looks healthy.\n\n**Release notes draft**\n- Keep prompt navigation shortcuts unchanged across platforms.\n- All built-in channel plugins are already migrated off deprecated settings fields.\n- Ready to summarize the release into UX polish, runtime stability, and mobile layout updates.",
          createdAt: 1_700_000_003_000,
        },
      ];

  return (
    <main className="thread-workspace relative flex min-w-0 flex-col overflow-hidden bg-background" style={{ height: "100dvh" }}>
      <ThreadHeader
        title={zh ? "v0.9.4 发布核对" : "v0.9.4 Release Review"}
        hideTitle
        theme={dark ? "dark" : "light"}
        onToggleSidebar={() => {}}
        onToggleTheme={() => setDark((value) => !value)}
        sessionInfoAction={<Button variant="ghost" size="icon" aria-label="Session details"><CalendarClock className="h-3.5 w-3.5" /></Button>}
        promptNavigatorAction={<Button variant="ghost" size="icon" aria-label="Conversation navigation"><ListFilter className="h-3.5 w-3.5" /></Button>}
      />
      <ComposerUsagePopover context={{ contextTokens: 24_180, contextWindowTokens: 200_000 }} rounds={[]}>
        {(renderContextUsage) => (
          <ThreadViewport
            messages={messages}
            isStreaming={false}
            conversationReady
            conversationKey="websocket:long-user-message-preview"
            hasMoreBefore={false}
            showScrollToBottomButton
            composer={(
              <ThreadComposer
                variant="thread"
                onSend={() => {}}
                modelLabel="claude-sonnet-4"
                modelProvider="anthropic"
                onTranscribeAudio={async () => ""}
                renderContextUsage={renderContextUsage}
                workspaceScope={scope}
                workspaceDefaultScope={initialScope}
                workspaceControls={catalog.controls}
                workspaceProjectLocked
                onWorkspaceScopeChange={setScope}
                onLoadWorkspaceProjects={async () => catalog}
                onResolveWorkspaceProject={async (path) => ({ path, name: "nanobot" })}
                onFavoriteWorkspaceProject={async () => []}
                onBrowseWorkspaceDirectories={async (path) => ({ path, parent: null, entries: [], truncated: false, host: "preview", platform: "Linux" })}
              />
            )}
          />
        )}
      </ComposerUsagePopover>
    </main>
  );
}
