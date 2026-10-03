import {
  BoxRenderable,
  RGBA,
  TextareaRenderable,
  TextRenderable,
  type CliRenderer,
  type PasteEvent,
  type SyntaxStyle,
} from "@opentui/core"

import type { QueuePreview } from "../composer/queue-preview"
import type { BranchMenu } from "../menus/branch-menu"
import type { CommandMenu } from "../menus/command-menu"
import type { MentionMenu } from "../menus/mention-menu"
import type { SessionMenu } from "../menus/session-menu"
import type { SkillMenu } from "../menus/skill-menu"
import type { Transcript } from "../rendering/transcript"
import type { ContextPanel } from "../views/context-panel"
import type { DiffViewer } from "../views/diff-viewer"
import type { RecoveryNotice } from "../views/recovery-notice"
import type { RuntimeControls } from "../views/runtime-controls"
import type { UsagePanel } from "../views/usage-panel"
import type { Palette } from "./theme"

export const COMPOSER_PLACEHOLDER = "Ask nanobot anything"
export const ACTIVE_COMPOSER_PLACEHOLDER = "Enter send now · Tab send next"
export const COMPACT_ACTIVE_COMPOSER_PLACEHOLDER = "Enter now · Tab next"

const TRANSCRIPT_EDGE_INSET = 1
const TRANSCRIPT_TEXT_INSET = TRANSCRIPT_EDGE_INSET + 2

interface LayoutComponents {
  transcript: Transcript
  commandMenu: CommandMenu
  sessionMenu: SessionMenu
  mentionMenu: MentionMenu
  skillMenu: SkillMenu
  branchMenu: BranchMenu
  contextPanel: ContextPanel
  usagePanel: UsagePanel
  runtimeControls: RuntimeControls
  queuePreview: QueuePreview
  recoveryNotice: RecoveryNotice
  diffViewer: DiffViewer
}

interface LayoutHandlers {
  onPrimaryMouseDown(): boolean
  onComposerCursorChange(): void
  onComposerContentChange(): void
  onComposerPointer(): void
  onSubmit(): void
  onPaste(event: PasteEvent): void
}

export interface AppLayout {
  shell: BoxRenderable
  title: BoxRenderable
  composerFrame: BoxRenderable
  composer: TextareaRenderable
  status: TextRenderable
  meta: TextRenderable
}

export function createAppLayout(
  renderer: CliRenderer,
  palette: Palette,
  composerSyntax: SyntaxStyle,
  composerSurface: RGBA,
  components: LayoutComponents,
  handlers: LayoutHandlers,
): AppLayout {
  // The terminal owns its canvas. Keeping the default-background intent is
  // essential in embedded terminals, where painting our own near-black RGB
  // only colors occupied cells and turns long output into dark strips.
  renderer.setBackgroundColor(RGBA.defaultBackground())
  const shell = new BoxRenderable(renderer, {
    id: "nanobot-tui-footer",
    width: "100%",
    height: "100%",
    paddingLeft: 1,
    paddingRight: 1,
    flexDirection: "column",
    backgroundColor: RGBA.defaultBackground(),
    onMouseDown: (event) => {
      if (event.button !== 0) return
      if (handlers.onPrimaryMouseDown()) event.preventDefault()
      // Selection belongs to transcript/input content, never to empty chrome.
      // Clearing it here prevents default-background cells from lingering as
      // opaque blocks in terminals with differential repainting.
      if (event.target && !event.target.selectable) renderer.clearSelection()
    },
  })
  const title = new BoxRenderable(renderer, {
    id: "nanobot-tui-title",
    width: "100%",
    height: 1,
    flexShrink: 0,
    flexDirection: "row",
    alignItems: "center",
    paddingLeft: TRANSCRIPT_TEXT_INSET,
    backgroundColor: RGBA.defaultBackground(),
  })
  title.add(components.runtimeControls.modelText)
  title.add(components.runtimeControls.accessText)
  title.add(components.runtimeControls.contextText)

  const composerFrame = new BoxRenderable(renderer, {
    id: "nanobot-tui-composer-frame",
    minHeight: 1,
    flexShrink: 0,
    marginLeft: TRANSCRIPT_EDGE_INSET,
    border: ["left"],
    borderColor: palette.accent,
    paddingLeft: 1,
    paddingRight: 1,
    backgroundColor: composerSurface,
  })
  const composer = new TextareaRenderable(renderer, {
    id: "nanobot-tui-composer",
    width: "100%",
    minHeight: 1,
    maxHeight: 8,
    wrapMode: "word",
    placeholder: COMPOSER_PLACEHOLDER,
    placeholderColor: palette.muted,
    textColor: palette.text,
    focusedTextColor: palette.text,
    backgroundColor: composerSurface,
    focusedBackgroundColor: composerSurface,
    cursorColor: palette.accent,
    syntaxStyle: composerSyntax,
    // A steady line cursor avoids the block-cell trails produced by some
    // terminals when a retained full-screen UI redraws around the composer.
    cursorStyle: { style: "line", blinking: false },
    showCursor: true,
    keyBindings: [
      { name: "return", shift: true, action: "newline" },
      { name: "return", meta: true, action: "newline" },
      { name: "return", ctrl: true, action: "newline" },
      { name: "kpenter", shift: true, action: "newline" },
      { name: "kpenter", meta: true, action: "newline" },
      { name: "kpenter", ctrl: true, action: "newline" },
      { name: "j", ctrl: true, action: "newline" },
      { name: "linefeed", action: "newline" },
      { name: "return", action: "submit" },
      { name: "kpenter", action: "submit" },
    ],
    onCursorChange: handlers.onComposerCursorChange,
    onContentChange: handlers.onComposerContentChange,
    onMouseDown: () => queueMicrotask(handlers.onComposerPointer),
    onMouseUp: () => queueMicrotask(handlers.onComposerPointer),
    onMouseDrag: () => queueMicrotask(handlers.onComposerPointer),
    onMouseDragEnd: () => queueMicrotask(handlers.onComposerPointer),
    // IMEs may commit their final composed glyph after Enter. Matching the
    // OpenCode/OpenTUI integration, defer twice before reading plainText.
    onSubmit: handlers.onSubmit,
    onPaste: handlers.onPaste,
  })
  const status = new TextRenderable(renderer, {
    id: "nanobot-tui-status",
    content: "Getting ready…",
    fg: palette.muted,
    height: 1,
    width: "auto",
    minWidth: 0,
    flexGrow: 1,
    flexShrink: 1,
    selectable: false,
  })
  const meta = new TextRenderable(renderer, {
    id: "nanobot-tui-meta",
    content: "",
    fg: palette.faint,
    height: 1,
    width: "auto",
    flexShrink: 1,
    selectable: false,
  })
  const statusRow = new BoxRenderable(renderer, {
    id: "nanobot-tui-status-row",
    width: "100%",
    height: 1,
    flexShrink: 0,
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 2,
    paddingLeft: TRANSCRIPT_TEXT_INSET,
  })
  composerFrame.add(composer)
  statusRow.add(status)
  statusRow.add(meta)

  shell.add(components.transcript.root)
  shell.add(components.commandMenu.root)
  shell.add(components.sessionMenu.root)
  shell.add(components.mentionMenu.root)
  shell.add(components.skillMenu.root)
  shell.add(components.branchMenu.root)
  shell.add(components.contextPanel.root)
  shell.add(components.usagePanel.root)
  shell.add(components.runtimeControls.menuRoot)
  shell.add(title)
  shell.add(components.queuePreview.root)
  shell.add(components.recoveryNotice.root)
  shell.add(composerFrame)
  shell.add(statusRow)
  shell.add(components.diffViewer.root)

  return { shell, title, composerFrame, composer, status, meta }
}
