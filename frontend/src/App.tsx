import { useState, type FC } from "react";
import { MenuIcon, PanelLeftIcon } from "lucide-react";
import {
  AssistantRuntimeProvider,
  CompositeAttachmentAdapter,
  SimpleImageAttachmentAdapter,
  SimpleTextAttachmentAdapter,
  type AttachmentAdapter,
} from "@assistant-ui/react";
import { useDataStreamRuntime } from "@assistant-ui/react-data-stream";
import { Thread } from "@/components/thread";
import { ThreadList } from "@/components/thread-list";
import { TooltipIconButton } from "@/components/tooltip-icon-button";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

/** MIME types that are safe to read as text. */
const TEXT_MIMES = new Set([
  "application/json",
  "application/xml",
  "application/javascript",
  "application/typescript",
  "application/x-yaml",
  "application/x-sh",
  "application/sql",
]);

function isTextFile(file: File): boolean {
  if (file.type.startsWith("text/")) return true;
  if (TEXT_MIMES.has(file.type)) return true;
  // Fall back to extension check for files with no MIME or generic MIME
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  const textExts = new Set([
    "json", "xml", "yaml", "yml", "toml", "ini", "cfg", "conf",
    "sh", "bash", "zsh", "fish", "ps1", "bat", "cmd",
    "js", "ts", "jsx", "tsx", "mjs", "cjs",
    "py", "rb", "go", "rs", "java", "kt", "scala", "c", "cpp", "h", "hpp",
    "cs", "swift", "r", "lua", "pl", "php",
    "sql", "graphql", "gql",
    "md", "mdx", "rst", "txt", "log", "env",
    "css", "scss", "sass", "less",
    "html", "htm", "svg",
    "csv", "tsv",
  ]);
  return textExts.has(ext);
}

/** Catch-all adapter: accepts any file not matched by image/text adapters. */
const fallbackFileAdapter: AttachmentAdapter = {
  accept: "*",
  async add(state) {
    return {
      id: state.file.name,
      type: "document" as const,
      name: state.file.name,
      contentType: state.file.type || "application/octet-stream",
      file: state.file,
      status: { type: "requires-action" as const, reason: "composer-send" as const },
    };
  },
  async send(attachment) {
    const file = attachment.file!;
    if (isTextFile(file)) {
      // Text files: read as text and wrap in <attachment> tags
      const text = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = (error) => reject(error);
        reader.readAsText(file);
      });
      return {
        ...attachment,
        status: { type: "complete" as const },
        content: [
          {
            type: "text" as const,
            text: `<attachment name="${attachment.name}">\n${text}\n</attachment>`,
          },
        ],
      };
    }
    // Binary files: send as base64 data URI via the file content part
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = (error) => reject(error);
      reader.readAsDataURL(file);
    });
    return {
      ...attachment,
      status: { type: "complete" as const },
      content: [
        {
          type: "file" as const,
          data: dataUrl,
          mimeType: file.type || "application/octet-stream",
        } as any,
        {
          type: "text" as const,
          text: `[Attached binary file: ${attachment.name}]`,
        },
      ],
    };
  },
  async remove() {},
};

const Logo: FC = () => {
  return (
    <div className="flex items-center gap-2 px-2 font-medium text-sm">
      <span className="text-xl">🤖</span>
      <span className="text-foreground/90">LangostIA</span>
    </div>
  );
};

const Sidebar: FC<{ collapsed?: boolean }> = ({ collapsed }) => {
  return (
    <aside
      className={cn(
        "flex h-full flex-col bg-muted/30 transition-all duration-200",
        collapsed ? "w-0 overflow-hidden opacity-0" : "w-65 opacity-100",
      )}
    >
      <div className="flex h-14 shrink-0 items-center px-4">
        <Logo />
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <ThreadList />
      </div>
    </aside>
  );
};

const MobileSidebar: FC = () => {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-9 shrink-0 md:hidden"
        >
          <MenuIcon className="size-4" />
          <span className="sr-only">Toggle menu</span>
        </Button>
      </SheetTrigger>
      <SheetContent side="left" className="w-70 p-0">
        <div className="flex h-14 items-center px-4">
          <Logo />
        </div>
        <div className="p-3">
          <ThreadList />
        </div>
      </SheetContent>
    </Sheet>
  );
};

const Header: FC<{
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}> = ({ sidebarCollapsed, onToggleSidebar }) => {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 px-4">
      <MobileSidebar />
      <TooltipIconButton
        variant="ghost"
        tooltip={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
        side="bottom"
        onClick={onToggleSidebar}
        className="hidden size-9 md:flex"
      >
        <PanelLeftIcon className="size-4" />
      </TooltipIconButton>
    </header>
  );
};

export default function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const runtime = useDataStreamRuntime({
    api: "/api/chat",
    protocol: "data-stream",
    adapters: {
      attachments: new CompositeAttachmentAdapter([
        new SimpleImageAttachmentAdapter(),
        new SimpleTextAttachmentAdapter(),
        fallbackFileAdapter,
      ]),
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex h-screen w-full bg-background">
        <div className="hidden md:block">
          <Sidebar collapsed={sidebarCollapsed} />
        </div>
        <div className="flex flex-1 flex-col overflow-hidden">
          <Header
            sidebarCollapsed={sidebarCollapsed}
            onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
          />
          <main className="flex-1 overflow-hidden">
            <Thread />
          </main>
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
}
