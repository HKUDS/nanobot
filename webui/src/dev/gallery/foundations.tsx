import { useState } from "react";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input, SearchInput } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ToggleButton } from "@/components/ui/toggle-button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { ComboboxOption, useComboboxNavigation } from "@/components/ui/combobox";
import { ControlChevron } from "@/components/ui/control-chevron";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { HoverHint, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, TruncatedTextTooltip } from "@/components/ui/tooltip";
import { Disclosure } from "@/components/ui/disclosure";
import { ExpandableText } from "@/components/ui/expandable-text";
import { StreamingLabelSheen } from "@/components/ui/streaming-label-sheen";
import { ImageViewport } from "@/components/ui/image-viewport";
import { Sample, type ComponentExample } from "./example";

function Buttons() {
  const [clicks, setClicks] = useState(0);
  return <div className="space-y-6">
    <Sample label="Variants · 同一个按钮的不同样式">
      <div className="flex flex-wrap items-center gap-3">
        {(["default", "secondary", "outline", "ghost", "destructive", "link"] as const).map((variant) =>
          <Button key={variant} variant={variant} onClick={() => setClicks((value) => value + 1)}>{variant}</Button>)}
        <Button variant="icon" size="icon" aria-label="Add example" onClick={() => setClicks((value) => value + 1)}><Plus className="h-4 w-4" /></Button>
      </div>
    </Sample>
    <Sample label="Sizes · 尺寸">
      <div className="flex flex-wrap items-center gap-3">
        {(["sm", "default", "control", "lg"] as const).map((size) =>
          <Button key={size} size={size} variant="outline" onClick={() => setClicks((value) => value + 1)}>{size}</Button>)}
        <Button disabled>Unavailable</Button>
      </div>
    </Sample>
    <p role="status" className="text-sm text-muted-foreground">Button clicks: {clicks}</p>
  </div>;
}

function Inputs() {
  return <div className="grid gap-5 sm:grid-cols-2">
    <Sample label="Default"><Input aria-label="Example name" placeholder="Project name" /></Sample>
    <Sample label="Search"><SearchInput aria-label="Example search" placeholder="Search projects" /></Sample>
    <Sample label="Invalid"><Input aria-label="Invalid name" aria-invalid="true" aria-describedby="gallery-input-error" defaultValue="" />
      <p id="gallery-input-error" className="text-xs text-destructive">Enter a project name.</p></Sample>
    <Sample label="Disabled"><Input aria-label="Disabled name" disabled defaultValue="Unavailable" /></Sample>
  </div>;
}

function Textareas() {
  return <div className="grid gap-5 sm:grid-cols-2">
    <Textarea aria-label="Example notes" defaultValue="Write a short note…" />
    <Textarea aria-label="Disabled notes" disabled defaultValue="Read-only preview" />
  </div>;
}

function Switches() {
  const [checked, setChecked] = useState(false);
  return <div className="space-y-5">
    <div className="flex items-center justify-between gap-4 text-sm"><span>Enable example</span>
      <ToggleButton checked={checked} onChange={setChecked} label="Enable example" /></div>
    <p role="status" className="text-sm text-muted-foreground">{checked ? "Enabled" : "Disabled"}</p>
    <div className="flex gap-8">
      <ToggleButton checked disabled onChange={() => {}} label="Unavailable enabled switch" />
      <ToggleButton checked={false} disabled onChange={() => {}} label="Unavailable disabled switch" />
    </div>
  </div>;
}

function Selects() {
  const [value, setValue] = useState("default");
  return <div className="flex flex-wrap items-center gap-4">
    <Select value={value} onValueChange={setValue}>
      <SelectTrigger aria-label="Example model" className="min-w-40"><SelectValue /></SelectTrigger>
      <SelectContent><SelectItem value="default">Default</SelectItem><SelectItem value="fast">Fast</SelectItem>
        <SelectItem value="offline" disabled>Unavailable</SelectItem></SelectContent>
    </Select>
    <Select disabled value="default"><SelectTrigger aria-label="Disabled model"><SelectValue /></SelectTrigger>
      <SelectContent><SelectItem value="default">Default</SelectItem></SelectContent></Select>
    <p role="status" className="text-sm text-muted-foreground">Selected: {value}</p>
  </div>;
}

function Segments() {
  const [value, setValue] = useState("day");
  return <div className="space-y-4">
    <SegmentedControl value={value} onChange={setValue} mode="tabs" ariaLabel="Example period"
      options={[{ value: "day", label: "Day" }, { value: "week", label: "Week" }, { value: "month", label: "Month" }]} />
    <p role="status" className="text-sm text-muted-foreground">Selected period: {value}</p>
  </div>;
}

function Comboboxes() {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("Alpha");
  const [open, setOpen] = useState(false);
  const values = ["Alpha", "Beta", "Gamma"].filter((name) => name.toLowerCase().includes(query.toLowerCase()));
  const select = (value: string) => { setSelected(value); setQuery(value); setOpen(false); };
  const navigation = useComboboxNavigation({ open, values, selectedValue: selected, onSelect: select, onClose: () => setOpen(false) });
  return <div className="max-w-sm space-y-3">
    <Input {...navigation.inputProps} aria-label="Search example options" value={query} placeholder="Type or use arrow keys"
      onFocus={() => setOpen(true)} onChange={(event) => { setQuery(event.target.value); setOpen(true); }} />
    {open && values.length > 0 ? <div {...navigation.listProps} aria-label="Example options" className="rounded-control border p-1">
      {values.map((value) => <ComboboxOption key={value} {...navigation.getOptionProps(value)}>{value}</ComboboxOption>)}
    </div> : null}
    {open && values.length === 0 ? <p role="status" className="text-sm text-muted-foreground">No matching options</p> : null}
    <p className="text-sm text-muted-foreground">Selected option: {selected}</p>
  </div>;
}

function Dialogs() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("Nanobot");
  const [draft, setDraft] = useState(name);
  return <div className="space-y-4">
    <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (next) setDraft(name); }}>
      <DialogTrigger asChild><Button variant="outline">Open dialog</Button></DialogTrigger>
      <DialogContent><DialogHeader><DialogTitle>Edit example label</DialogTitle>
        <DialogDescription>Changes apply only to this preview.</DialogDescription></DialogHeader>
        <Input aria-label="Example label" value={draft} onChange={(event) => setDraft(event.target.value)} />
        <Selects />
        <DialogFooter><DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
          <Button onClick={() => { setName(draft); setOpen(false); }}>Save label</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <p role="status" className="text-sm text-muted-foreground">Saved label: {name}</p>
  </div>;
}

function Alerts() {
  const [removed, setRemoved] = useState(false);
  const [open, setOpen] = useState(false);
  return <div className="space-y-4">
    <Button variant="destructive" onClick={() => setOpen(true)}>Remove example</Button>
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Remove this example?</AlertDialogTitle>
        <AlertDialogDescription>This changes only the preview state.</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={() => setRemoved(true)}>Confirm removal</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    <p role="status" className="text-sm text-muted-foreground">{removed ? "Example removed." : "Example available."}</p>
  </div>;
}

function Sheets() {
  return <Sheet><SheetTrigger asChild><Button variant="outline">Open sheet</Button></SheetTrigger>
    <SheetContent><SheetTitle>Example side panel</SheetTitle><SheetDescription>Supporting controls beside the current page.</SheetDescription>
      <div className="mt-6"><Input aria-label="Panel notes" placeholder="Try editing here" /></div></SheetContent>
  </Sheet>;
}

function Popovers() {
  return <Popover><PopoverTrigger asChild><Button variant="outline">Open popover</Button></PopoverTrigger>
    <PopoverContent className="w-64 p-4"><label className="space-y-2 text-sm"><span>Quick note</span><Input aria-label="Quick note" /></label></PopoverContent>
  </Popover>;
}

function Menus() {
  const [density, setDensity] = useState("comfortable");
  const [action, setAction] = useState("None");
  return <div className="space-y-4">
    <DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline">View options</Button></DropdownMenuTrigger>
      <DropdownMenuContent><DropdownMenuLabel>Layout</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={density} onValueChange={setDensity}>
          <DropdownMenuRadioItem value="comfortable">Comfortable</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="compact">Compact</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup><DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => setAction("Rename")}>Rename</DropdownMenuItem>
        <DropdownMenuSub><DropdownMenuSubTrigger>More actions</DropdownMenuSubTrigger><DropdownMenuSubContent>
          <DropdownMenuItem onSelect={() => setAction("Duplicate")}>Duplicate</DropdownMenuItem>
        </DropdownMenuSubContent></DropdownMenuSub>
        <DropdownMenuItem disabled>Unavailable</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    <p role="status" className="text-sm text-muted-foreground">Density: {density}. Action: {action}.</p>
  </div>;
}

function Tooltips() {
  return <div className="flex flex-wrap items-center gap-4">
    <TooltipProvider><Tooltip><TooltipTrigger asChild><Button variant="outline">Primitive tooltip</Button></TooltipTrigger>
      <TooltipContent>Shared pointer delay and immediate keyboard focus.</TooltipContent></Tooltip></TooltipProvider>
    <HoverHint content="A composed hint with the same focus and pointer behavior."><Button variant="outline">Hover hint</Button></HoverHint>
  </div>;
}

function TruncatedText() {
  return <div className="space-y-4">
    <TruncatedTextTooltip tabIndex={0} className="block max-w-48 text-sm" text="A long project name whose full text stays available on focus" />
    <TruncatedTextTooltip tabIndex={0} className="block max-w-48 text-sm" text="Short name" />
  </div>;
}

function Disclosures() {
  return <Disclosure summary={<span className="text-sm font-medium">Show advanced options</span>}
    summaryClassName="rounded-control border p-3" contentClassName="space-y-3 p-3">
    <p className="text-sm text-muted-foreground">This draft survives closing and reopening.</p>
    <Input aria-label="Disclosure draft" defaultValue="Keep this draft" />
  </Disclosure>;
}

function Expandable() {
  const [expanded, setExpanded] = useState(false);
  return <div className="max-w-sm space-y-3">
    <ExpandableText expanded={expanded} lines={2} id="gallery-expandable" className="text-sm leading-6">
      {"A longer activity description can stay compact while preserving its full text. Expand this example to read all of it, then collapse it again. The same paragraph remains mounted throughout the animation, so selection and layout do not jump between duplicate copies."}
    </ExpandableText>
    <Button variant="outline" size="sm" aria-expanded={expanded} aria-controls="gallery-expandable"
      onClick={() => setExpanded((value) => !value)}>{expanded ? "Show less" : "Show more"}</Button>
  </div>;
}

function StreamingLabels() {
  const [active, setActive] = useState(true);
  return <div className="space-y-4">
    <ToggleButton label="Animate label" checked={active} onChange={setActive} />
    <StreamingLabelSheen active={active}>Working through the next step…</StreamingLabelSheen>
  </div>;
}

function ImageViewports() {
  return <div className="flex h-80 max-w-xl flex-col rounded-lg border p-3">
    <ImageViewport src="/brand/nanobot_icon_512.png" alt="Nanobot" className="flex-1" />
  </div>;
}

const base = "webui/src/components/ui/";
export const foundationExamples: ComponentExample[] = [
  { title: "Button · 按钮", files: ["button"], Preview: Buttons,
    description: "One button, several appearances and sizes. 同一组件通过选项变化。",
    options: "variant changes appearance; size changes dimensions; disabled blocks interaction; onClick belongs to the caller.",
    code: '<Button variant="destructive" size="sm" onClick={removeItem}>Remove</Button>' },
  { title: "Input · 输入框", files: ["input"], Preview: Inputs,
    description: "Text entry and the shared search-field variant.", options: "Use Input for regular fields and SearchInput for search. Supply a label and describe invalid input.",
    code: '<Input aria-label="Project name" value={name} onChange={event => setName(event.target.value)} />' },
  { title: "Textarea · 多行输入", files: ["textarea"], Preview: Textareas,
    description: "Multiline text using the shared focus treatment.", options: "Accepts native textarea props: value, onChange, rows and disabled.", code: '<Textarea aria-label="Notes" value={notes} onChange={event => setNotes(event.target.value)} />' },
  { title: "ToggleButton · 开关", files: ["toggle-button"], Preview: Switches,
    description: "A controlled on/off switch shared by settings, workspaces and channels.", options: "The caller owns checked and onChange. label supplies its accessible name.", code: '<ToggleButton checked={enabled} onChange={setEnabled} label="Enable feature" />' },
  { title: "Select · 选择器", files: ["select"], Preview: Selects,
    description: "A single choice with keyboard navigation and disabled options.", options: "Compose Select, SelectTrigger, SelectValue, SelectContent and SelectItem. The root owns value/onValueChange.",
    code: '<Select value={value} onValueChange={setValue}>\n  <SelectTrigger aria-label="Model"><SelectValue /></SelectTrigger>\n  <SelectContent><SelectItem value="default">Default</SelectItem></SelectContent>\n</Select>' },
  { title: "SegmentedControl · 分段选择", files: ["segmented-control"], Preview: Segments,
    description: "A short, always-visible set of choices.", options: 'value, options and onChange are controlled. mode="tabs" adds arrow-key tab navigation.',
    code: '<SegmentedControl value={period} onChange={setPeriod} options={[{ value: "day", label: "Day" }, { value: "week", label: "Week" }]} ariaLabel="Period" />' },
  { title: "Combobox · 搜索选择", files: ["combobox"], Preview: Comboboxes,
    description: "Searchable options with shared keyboard and pointer navigation.", options: "useComboboxNavigation supplies input/list/option props; the caller filters values and owns selection.",
    code: 'const nav = useComboboxNavigation({ open, values, selectedValue, onSelect, onClose });\n<Input {...nav.inputProps} aria-label="Search" />\n<div {...nav.listProps}>\n  {values.map(value => <ComboboxOption key={value} {...nav.getOptionProps(value)}>{value}</ComboboxOption>)}\n</div>' },
  { title: "ControlChevron · 控件箭头", files: ["control-chevron"], Preview: () => <ControlChevron />,
    description: "The shared chevron used by selection controls.", options: "className may adjust placement. The icon is decorative; the owning control supplies its accessible name.", code: '<ControlChevron />' },
  { title: "Dialog · 对话框", files: ["dialog"], Preview: Dialogs,
    description: "A modal editor with staged changes, nested selection and focus return.", options: "The caller owns open/onOpenChange and draft/save behavior. Always provide DialogTitle and a description when useful.",
    code: '<Dialog open={open} onOpenChange={setOpen}>\n  <DialogTrigger asChild><Button>Edit</Button></DialogTrigger>\n  <DialogContent><DialogTitle>Edit item</DialogTitle><DialogDescription>Update this item.</DialogDescription>{editor}</DialogContent>\n</Dialog>' },
  { title: "AlertDialog · 确认对话框", files: ["alert-dialog"], Preview: Alerts,
    description: "An explicit confirmation with separate cancel and action controls.", options: "Compose title, description and footer; perform the action in AlertDialogAction's handler.",
    code: '<Button onClick={() => setOpen(true)}>Remove</Button>\n<AlertDialog open={open} onOpenChange={setOpen}>\n  <AlertDialogContent><AlertDialogTitle>Remove item?</AlertDialogTitle><AlertDialogDescription>This removes the item.</AlertDialogDescription><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={removeItem}>Remove</AlertDialogAction></AlertDialogContent>\n</AlertDialog>' },
  { title: "Sheet · 侧边面板", files: ["sheet"], Preview: Sheets,
    description: "A modal panel attached to an edge of the viewport.", options: "SheetContent supports side. Include SheetTitle and SheetDescription.",
    code: '<Sheet><SheetTrigger asChild><Button>Details</Button></SheetTrigger><SheetContent side="right"><SheetTitle>Details</SheetTitle><SheetDescription>Additional information.</SheetDescription>{content}</SheetContent></Sheet>' },
  { title: "Popover · 浮层", files: ["popover"], Preview: Popovers,
    description: "A small interactive surface anchored to its trigger.", options: "Compose trigger and content; open/onOpenChange can be controlled. Content follows the owning dialog's portal.",
    code: '<Popover><PopoverTrigger asChild><Button>Note</Button></PopoverTrigger><PopoverContent>{editor}</PopoverContent></Popover>' },
  { title: "DropdownMenu · 菜单", files: ["dropdown-menu"], Preview: Menus,
    description: "Actions, radio choices, nested menus and disabled entries.", options: "Use onSelect for actions and a radio group for a persistent choice.",
    code: '<DropdownMenu><DropdownMenuTrigger asChild><Button>Actions</Button></DropdownMenuTrigger><DropdownMenuContent><DropdownMenuItem onSelect={rename}>Rename</DropdownMenuItem></DropdownMenuContent></DropdownMenu>' },
  { title: "Tooltip / HoverHint · 提示", files: ["tooltip", "tooltip-primitives", "hover-hint"], Preview: Tooltips,
    description: "HoverHint composes the shared tooltip primitives; tooltip.tsx is their public import surface.", options: "Use HoverHint for ordinary hints. Keep essential errors visible. Hover and keyboard focus share the product's timing rules.",
    code: '<HoverHint content="Add an attachment"><Button size="icon" aria-label="Add attachment"><Plus /></Button></HoverHint>' },
  { title: "TruncatedTextTooltip · 截断提示", files: ["truncated-text-tooltip"], Preview: TruncatedText,
    description: "Shows a hint only when the measured text is truncated.", options: "Supply text and a constrained width. Add tabIndex when the text itself should receive keyboard focus.",
    code: '<TruncatedTextTooltip text={projectName} tabIndex={0} className="block max-w-48" />' },
  { title: "Disclosure · 折叠内容", files: ["disclosure"], Preview: Disclosures,
    description: "Expandable content that preserves child state while folded.", options: "Disclosure owns expansion; DisclosureContent accepts a controlled open prop for custom triggers.",
    code: '<Disclosure summary="Advanced options"><Input aria-label="Draft" defaultValue="Preserved" /></Disclosure>' },
  { title: "ExpandableText · 文本展开", files: ["expandable-text"], Preview: Expandable,
    description: "A line-limited preview of the same mounted text.", options: "The caller owns expanded. lines sets the collapsed line count; provide an accessible toggle.",
    code: '<ExpandableText expanded={expanded} lines={2} className="text-sm leading-6">{description}</ExpandableText>' },
  { title: "ImageViewport · 图像视口", files: ["image-viewport"], Preview: ImageViewports,
    description: "Image-local fit, zoom, pan and pinch controls.", options: "Supply a bounded className and remount for a different image identity. Set panWithArrows=false when a gallery owns arrow navigation.",
    code: '<div className="flex h-80 flex-col"><ImageViewport src={url} alt={label} className="flex-1" /></div>' },
  { title: "StreamingLabelSheen · 流光文字", files: ["streaming-label-sheen"], Preview: StreamingLabels,
    description: "A shared text animation for active thinking and tool labels.", options: "active controls animation. String or number children supply the glyph overlay; reduced-motion settings are respected.",
    code: '<StreamingLabelSheen active={running}>Working…</StreamingLabelSheen>' },
].map((example) => ({ ...example, files: example.files.map((file) => `${base}${file}.tsx`) }));
