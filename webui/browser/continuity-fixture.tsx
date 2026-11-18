import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { sidePanelSurfaceClassName } from "@/components/ui/floating-surface";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SidebarPanel } from "@/components/ui/sidebar-panel";

export function ContinuityFixture() {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  return <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-6 px-5 py-12">
    <h1 className="text-title">Interaction continuity</h1>
    <div className="flex flex-wrap gap-3">
      <DropdownMenu>
        <DropdownMenuTrigger asChild><Button variant="outline">Conversation actions</Button></DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuItem>Rename conversation</DropdownMenuItem>
          <DropdownMenuItem>Duplicate conversation</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Popover>
        <PopoverTrigger asChild><Button variant="outline">Quick note</Button></PopoverTrigger>
        <PopoverContent className="w-64 p-4" align="start"><Input aria-label="Quick note draft" placeholder="Write a note" /></PopoverContent>
      </Popover>
      <Button ref={trigger} variant="outline" onClick={() => setOpen(value => !value)} aria-expanded={open}>Toggle details</Button>
    </div>
    <section className="max-w-lg space-y-4 rounded-panel border p-5">
      <Disclosure summary="Advanced options" summaryClassName="text-control-label" contentClassName="pt-4">
        <Input aria-label="Advanced draft" placeholder="This draft survives folding" />
        <p className="mt-3 text-caption text-muted-foreground">The next row moves with the expanded content.</p>
      </Disclosure>
      <p data-testid="following-row" className="text-ui">The following row stays in the page flow.</p>
    </section>
    <div className="thread-preview-layout relative flex shrink-0 overflow-hidden rounded-panel border" style={{ height: 340 }}>
      <div className="min-w-0 flex-1 p-5">
        <p className="mb-3 text-control-label">Conversation stays in place</p>
        <Input aria-label="Conversation draft" placeholder="Your next message" />
      </div>
      <SidebarPanel open={open} width={420} aria-label="Details" contentClassName={sidePanelSurfaceClassName} header={<span className="text-control-label">Details</span>}
        onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); close(); } }}>
        <div className="space-y-4 p-5">
          <Input aria-label="Details draft" placeholder="Reopen during closing to keep editing" />
          <span aria-label="Activity" className="block size-4 animate-spin rounded-full border-2 border-current border-t-transparent motion-reduce:animate-none" />
          <Button variant="outline" onClick={close}>Close details</Button>
        </div>
      </SidebarPanel>
    </div>
  </main>;
}
