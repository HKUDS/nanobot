import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";

export function ThemeToggleFixture() {
  const { theme, toggle } = useTheme();
  return (
    <ThemeProvider theme={theme}>
      <main className="thread-workspace relative flex h-screen flex-col justify-center gap-8 bg-background px-6">
        <ThreadHeader title="Theme preview" hideTitle theme={theme} onToggleTheme={toggle} onToggleSidebar={() => {}} />
        <div className="workbench-body bg-background">
          <section className="workbench-pane flex flex-col gap-8 bg-background">
            <h1 data-testid="hero-greeting" className="text-center text-4xl text-foreground">Where should we start?</h1>
            <ThreadComposer variant="hero" onSend={() => {}} />
          </section>
        </div>
      </main>
    </ThemeProvider>
  );
}
