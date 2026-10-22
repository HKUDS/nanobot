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
import { useGalleryTranslation } from "./i18n";

function Buttons() {
  const { t } = useGalleryTranslation();
  const [clicks, setClicks] = useState(0);
  return <div className="space-y-6">
    <Sample label={t("controls.button.variants")}>
      <div className="flex flex-wrap items-center gap-3">
        {(["default", "accent", "secondary", "outline", "ghost", "destructive", "link"] as const).map((variant) =>
          <Button key={variant} variant={variant} onClick={() => setClicks((value) => value + 1)}>{variant}</Button>)}
        <Button variant="icon" size="icon" aria-label={t("controls.button.add")} onClick={() => setClicks((value) => value + 1)}><Plus className="h-4 w-4" /></Button>
      </div>
    </Sample>
    <Sample label={t("controls.button.sizes")}>
      <div className="flex flex-wrap items-center gap-3">
        {(["sm", "default", "control", "lg"] as const).map((size) =>
          <Button key={size} size={size} variant="outline" onClick={() => setClicks((value) => value + 1)}>{size}</Button>)}
        <Button disabled>{t("controls.common.unavailable")}</Button>
      </div>
    </Sample>
    <p role="status" className="text-sm text-muted-foreground">{t("controls.button.clicks", { count: clicks })}</p>
  </div>;
}

function Inputs() {
  const { t } = useGalleryTranslation();
  return <div className="grid gap-5 sm:grid-cols-2">
    <Sample label={t("settings.values.default", { ns: "common" })}><Input aria-label={t("controls.input.name")} placeholder={t("controls.input.projectName")} /></Sample>
    <Sample label={t("controls.input.search")}><SearchInput aria-label={t("controls.input.searchName")} placeholder={t("controls.input.searchProjects")} /></Sample>
    <Sample label={t("controls.input.invalid")}><Input aria-label={t("controls.input.invalidName")} aria-invalid="true" aria-describedby="gallery-input-error" defaultValue="" />
      <p id="gallery-input-error" className="text-xs text-destructive">{t("controls.input.required")}</p></Sample>
    <Sample label={t("settings.values.disabled", { ns: "common" })}><Input aria-label={t("controls.input.disabledName")} disabled value={t("controls.common.unavailable")} /></Sample>
  </div>;
}

function Textareas() {
  const { t } = useGalleryTranslation();
  return <div className="grid gap-5 sm:grid-cols-2">
    <Textarea aria-label={t("controls.textarea.notes")} defaultValue="Write a short note…" />
    <Textarea aria-label={t("controls.textarea.disabledNotes")} disabled value={t("controls.textarea.readOnly")} />
  </div>;
}

function Switches() {
  const { t } = useGalleryTranslation();
  const [checked, setChecked] = useState(false);
  return <div className="space-y-5">
    <div className="flex items-center justify-between gap-4 text-sm"><span>{t("controls.toggle.enable")}</span>
      <ToggleButton checked={checked} onChange={setChecked} label={t("controls.toggle.enable")} /></div>
    <p role="status" className="text-sm text-muted-foreground">{t(checked ? "settings.values.enabled" : "settings.values.disabled", { ns: "common" })}</p>
    <div className="flex gap-8">
      <ToggleButton checked disabled onChange={() => {}} label={t("controls.toggle.unavailableOn")} />
      <ToggleButton checked={false} disabled onChange={() => {}} label={t("controls.toggle.unavailableOff")} />
    </div>
  </div>;
}

function Selects() {
  const { t } = useGalleryTranslation();
  const [value, setValue] = useState("default");
  const labels: Record<string, string> = { default: t("settings.values.default", { ns: "common" }), fast: t("controls.select.fast") };
  return <div className="flex flex-wrap items-center gap-4">
    <Select value={value} onValueChange={setValue}>
      <SelectTrigger aria-label={t("controls.select.model")} className="min-w-40"><SelectValue /></SelectTrigger>
      <SelectContent><SelectItem value="default">{labels.default}</SelectItem><SelectItem value="fast">{labels.fast}</SelectItem>
        <SelectItem value="offline" disabled>{t("controls.common.unavailable")}</SelectItem></SelectContent>
    </Select>
    <Select disabled value="default"><SelectTrigger aria-label={t("controls.select.disabledModel")}><SelectValue /></SelectTrigger>
      <SelectContent><SelectItem value="default">{labels.default}</SelectItem></SelectContent></Select>
    <p role="status" className="text-sm text-muted-foreground">{t("controls.common.selected", { value: labels[value] })}</p>
  </div>;
}

function Segments() {
  const { t } = useGalleryTranslation();
  const [value, setValue] = useState("day");
  const options = ["day", "week", "month"].map((period) => ({ value: period, label: t(`controls.segmented.${period}`) }));
  return <div className="space-y-4">
    <SegmentedControl value={value} onChange={setValue} mode="tabs" ariaLabel={t("controls.segmented.period")} options={options} />
    <p role="status" className="text-sm text-muted-foreground">{t("controls.segmented.selected", { value: t(`controls.segmented.${value}`) })}</p>
  </div>;
}

function Comboboxes() {
  const { t } = useGalleryTranslation();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("Alpha");
  const [open, setOpen] = useState(false);
  const values = ["Alpha", "Beta", "Gamma"].filter((name) => name.toLowerCase().includes(query.toLowerCase()));
  const select = (value: string) => { setSelected(value); setQuery(value); setOpen(false); };
  const navigation = useComboboxNavigation({ open, values, selectedValue: selected, onSelect: select, onClose: () => setOpen(false) });
  return <div className="max-w-sm space-y-3">
    <Input {...navigation.inputProps} aria-label={t("controls.combobox.search")} value={query} placeholder={t("controls.combobox.placeholder")}
      onFocus={() => setOpen(true)} onChange={(event) => { setQuery(event.target.value); setOpen(true); }} />
    {open && values.length > 0 ? <div {...navigation.listProps} aria-label={t("controls.combobox.choices")} className="rounded-control border p-1">
      {values.map((value) => <ComboboxOption key={value} {...navigation.getOptionProps(value)}>{value}</ComboboxOption>)}
    </div> : null}
    {open && values.length === 0 ? <p role="status" className="text-sm text-muted-foreground">{t("controls.combobox.empty")}</p> : null}
    <p className="text-sm text-muted-foreground">{t("controls.combobox.selected", { value: selected })}</p>
  </div>;
}

function Dialogs() {
  const { t } = useGalleryTranslation();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("Nanobot");
  const [draft, setDraft] = useState(name);
  return <div className="space-y-4">
    <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (next) setDraft(name); }}>
      <DialogTrigger asChild><Button variant="outline">{t("controls.dialog.open")}</Button></DialogTrigger>
      <DialogContent><DialogHeader><DialogTitle>{t("controls.dialog.edit")}</DialogTitle>
        <DialogDescription>{t("controls.dialog.help")}</DialogDescription></DialogHeader>
        <Input aria-label={t("controls.dialog.label")} value={draft} onChange={(event) => setDraft(event.target.value)} />
        <Selects />
        <DialogFooter><DialogClose asChild><Button variant="outline">{t("settings.actions.cancel", { ns: "common" })}</Button></DialogClose>
          <Button onClick={() => { setName(draft); setOpen(false); }}>{t("controls.dialog.save")}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <p role="status" className="text-sm text-muted-foreground">{t("controls.dialog.saved", { name })}</p>
  </div>;
}

function Alerts() {
  const { t } = useGalleryTranslation();
  const [removed, setRemoved] = useState(false);
  const [open, setOpen] = useState(false);
  return <div className="space-y-4">
    <Button variant="destructive" onClick={() => setOpen(true)}>{t("controls.alert.remove")}</Button>
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{t("controls.alert.confirmTitle")}</AlertDialogTitle>
        <AlertDialogDescription>{t("controls.alert.help")}</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>{t("settings.actions.cancel", { ns: "common" })}</AlertDialogCancel>
          <AlertDialogAction onClick={() => setRemoved(true)}>{t("controls.alert.confirm")}</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    <p role="status" className="text-sm text-muted-foreground">{t(removed ? "controls.alert.removed" : "controls.alert.available")}</p>
  </div>;
}

function Sheets() {
  const { t } = useGalleryTranslation();
  return <Sheet><SheetTrigger asChild><Button variant="outline">{t("controls.sheet.open")}</Button></SheetTrigger>
    <SheetContent><SheetTitle>{t("controls.sheet.panelTitle")}</SheetTitle><SheetDescription>{t("controls.sheet.help")}</SheetDescription>
      <div className="mt-6"><Input aria-label={t("controls.sheet.notes")} placeholder={t("controls.sheet.placeholder")} /></div></SheetContent>
  </Sheet>;
}

function Popovers() {
  const { t } = useGalleryTranslation();
  return <Popover><PopoverTrigger asChild><Button variant="outline">{t("controls.popover.open")}</Button></PopoverTrigger>
    <PopoverContent className="w-64 p-4"><label className="space-y-2 text-sm"><span>{t("controls.popover.note")}</span><Input aria-label={t("controls.popover.note")} /></label></PopoverContent>
  </Popover>;
}

function Menus() {
  const { t } = useGalleryTranslation();
  const [density, setDensity] = useState("comfortable");
  const [action, setAction] = useState("none");
  return <div className="space-y-4">
    <DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline">{t("controls.menu.view")}</Button></DropdownMenuTrigger>
      <DropdownMenuContent><DropdownMenuLabel>{t("controls.menu.layout")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={density} onValueChange={setDensity}>
          <DropdownMenuRadioItem value="comfortable">{t("controls.menu.comfortable")}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="compact">{t("controls.menu.compact")}</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup><DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => setAction("rename")}>{t("controls.menu.rename")}</DropdownMenuItem>
        <DropdownMenuSub><DropdownMenuSubTrigger>{t("controls.menu.more")}</DropdownMenuSubTrigger><DropdownMenuSubContent>
          <DropdownMenuItem onSelect={() => setAction("duplicate")}>{t("controls.menu.duplicate")}</DropdownMenuItem>
        </DropdownMenuSubContent></DropdownMenuSub>
        <DropdownMenuItem disabled>{t("controls.common.unavailable")}</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    <p role="status" className="text-sm text-muted-foreground">{t("controls.menu.status", { density: t(`controls.menu.${density}`), action: t(`controls.menu.${action}`) })}</p>
  </div>;
}

function Tooltips() {
  const { t } = useGalleryTranslation();
  return <div className="flex flex-wrap items-center gap-4">
    <TooltipProvider><Tooltip><TooltipTrigger asChild><Button variant="outline">{t("controls.tooltip.primitive")}</Button></TooltipTrigger>
      <TooltipContent>{t("controls.tooltip.primitiveHelp")}</TooltipContent></Tooltip></TooltipProvider>
    <HoverHint content={t("controls.tooltip.hintHelp")}><Button variant="outline">{t("controls.tooltip.hint")}</Button></HoverHint>
  </div>;
}

function TruncatedText() {
  return <div className="space-y-4">
    <TruncatedTextTooltip tabIndex={0} className="block max-w-48 text-sm" text="A long project name whose full text stays available on focus" />
    <TruncatedTextTooltip tabIndex={0} className="block max-w-48 text-sm" text="Short name" />
  </div>;
}

function Disclosures() {
  const { t } = useGalleryTranslation();
  return <Disclosure summary={<span className="text-sm font-medium">{t("controls.disclosure.show")}</span>}
    summaryClassName="rounded-control border p-3" contentClassName="space-y-3 p-3">
    <p className="text-sm text-muted-foreground">{t("controls.disclosure.help")}</p>
    <Input aria-label={t("controls.disclosure.draft")} defaultValue="Keep this draft" />
  </Disclosure>;
}

function Expandable() {
  const { t } = useGalleryTranslation();
  const [expanded, setExpanded] = useState(false);
  return <div className="max-w-sm space-y-3">
    <ExpandableText expanded={expanded} lines={2} id="gallery-expandable" className="text-sm leading-6">
      {"A longer activity description can stay compact while preserving its full text. Expand this example to read all of it, then collapse it again. The same paragraph remains mounted throughout the animation, so selection and layout do not jump between duplicate copies."}
    </ExpandableText>
    <Button variant="outline" size="sm" aria-expanded={expanded} aria-controls="gallery-expandable"
      onClick={() => setExpanded((value) => !value)}>{t(expanded ? "controls.expandable.less" : "controls.expandable.more")}</Button>
  </div>;
}

function StreamingLabels() {
  const { t } = useGalleryTranslation();
  const [active, setActive] = useState(true);
  return <div className="space-y-4">
    <ToggleButton label={t("controls.streaming.animate")} checked={active} onChange={setActive} />
    <StreamingLabelSheen active={active}>{t("controls.streaming.working")}</StreamingLabelSheen>
  </div>;
}

function ImageViewports() {
  return <div className="flex h-80 max-w-xl flex-col rounded-lg border p-3">
    <ImageViewport src="/brand/nanobot_icon_512.png" alt="Nanobot" className="flex-1" />
  </div>;
}

const base = "webui/src/components/ui/";
export const foundationExamples: ComponentExample[] = [
  { title: "controls.button.title", files: ["button"], Preview: Buttons,
    description: "controls.button.description",
    options: "controls.button.options",
    code: '<Button variant="destructive" size="sm" onClick={removeItem}>Remove</Button>' },
  { title: "controls.input.title", files: ["input"], Preview: Inputs,
    description: "controls.input.description", options: "controls.input.options",
    code: '<Input aria-label="Project name" value={name} onChange={event => setName(event.target.value)} />' },
  { title: "controls.textarea.title", files: ["textarea"], Preview: Textareas,
    description: "controls.textarea.description", options: "controls.textarea.options", code: '<Textarea aria-label="Notes" value={notes} onChange={event => setNotes(event.target.value)} />' },
  { title: "controls.toggle.title", files: ["toggle-button"], Preview: Switches,
    description: "controls.toggle.description", options: "controls.toggle.options", code: '<ToggleButton checked={enabled} onChange={setEnabled} label="Enable feature" />' },
  { title: "controls.select.title", files: ["select"], Preview: Selects,
    description: "controls.select.description", options: "controls.select.options",
    code: '<Select value={value} onValueChange={setValue}>\n  <SelectTrigger aria-label="Model"><SelectValue /></SelectTrigger>\n  <SelectContent><SelectItem value="default">Default</SelectItem></SelectContent>\n</Select>' },
  { title: "controls.segmented.title", files: ["segmented-control"], Preview: Segments,
    description: "controls.segmented.description", options: "controls.segmented.options",
    code: '<SegmentedControl value={period} onChange={setPeriod} options={[{ value: "day", label: "Day" }, { value: "week", label: "Week" }]} ariaLabel="Period" />' },
  { title: "controls.combobox.title", files: ["combobox"], Preview: Comboboxes,
    description: "controls.combobox.description", options: "controls.combobox.options",
    code: 'const nav = useComboboxNavigation({ open, values, selectedValue, onSelect, onClose });\n<Input {...nav.inputProps} aria-label="Search" />\n<div {...nav.listProps}>\n  {values.map(value => <ComboboxOption key={value} {...nav.getOptionProps(value)}>{value}</ComboboxOption>)}\n</div>' },
  { title: "controls.chevron.title", files: ["control-chevron"], Preview: () => <ControlChevron />,
    description: "controls.chevron.description", options: "controls.chevron.options", code: '<ControlChevron />' },
  { title: "controls.dialog.title", files: ["dialog"], Preview: Dialogs,
    description: "controls.dialog.description", options: "controls.dialog.options",
    code: '<Dialog open={open} onOpenChange={setOpen}>\n  <DialogTrigger asChild><Button>Edit</Button></DialogTrigger>\n  <DialogContent><DialogTitle>Edit item</DialogTitle><DialogDescription>Update this item.</DialogDescription>{editor}</DialogContent>\n</Dialog>' },
  { title: "controls.alert.title", files: ["alert-dialog"], Preview: Alerts,
    description: "controls.alert.description", options: "controls.alert.options",
    code: '<Button onClick={() => setOpen(true)}>Remove</Button>\n<AlertDialog open={open} onOpenChange={setOpen}>\n  <AlertDialogContent><AlertDialogTitle>Remove item?</AlertDialogTitle><AlertDialogDescription>This removes the item.</AlertDialogDescription><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={removeItem}>Remove</AlertDialogAction></AlertDialogContent>\n</AlertDialog>' },
  { title: "controls.sheet.title", files: ["sheet"], Preview: Sheets,
    description: "controls.sheet.description", options: "controls.sheet.options",
    code: '<Sheet><SheetTrigger asChild><Button>Details</Button></SheetTrigger><SheetContent side="right"><SheetTitle>Details</SheetTitle><SheetDescription>Additional information.</SheetDescription>{content}</SheetContent></Sheet>' },
  { title: "controls.popover.title", files: ["popover"], Preview: Popovers,
    description: "controls.popover.description", options: "controls.popover.options",
    code: '<Popover><PopoverTrigger asChild><Button>Note</Button></PopoverTrigger><PopoverContent>{editor}</PopoverContent></Popover>' },
  { title: "controls.menu.title", files: ["dropdown-menu"], Preview: Menus,
    description: "controls.menu.description", options: "controls.menu.options",
    code: '<DropdownMenu><DropdownMenuTrigger asChild><Button>Actions</Button></DropdownMenuTrigger><DropdownMenuContent><DropdownMenuItem onSelect={rename}>Rename</DropdownMenuItem></DropdownMenuContent></DropdownMenu>' },
  { title: "controls.tooltip.title", files: ["tooltip", "tooltip-primitives", "hover-hint"], Preview: Tooltips,
    description: "controls.tooltip.description", options: "controls.tooltip.options",
    code: '<HoverHint content="Add an attachment"><Button size="icon" aria-label="Add attachment"><Plus /></Button></HoverHint>' },
  { title: "controls.truncated.title", files: ["truncated-text-tooltip"], Preview: TruncatedText,
    description: "controls.truncated.description", options: "controls.truncated.options",
    code: '<TruncatedTextTooltip text={projectName} tabIndex={0} className="block max-w-48" />' },
  { title: "controls.disclosure.title", files: ["disclosure"], Preview: Disclosures,
    description: "controls.disclosure.description", options: "controls.disclosure.options",
    code: '<Disclosure summary="Advanced options"><Input aria-label="Draft" defaultValue="Preserved" /></Disclosure>' },
  { title: "controls.expandable.title", files: ["expandable-text"], Preview: Expandable,
    description: "controls.expandable.description", options: "controls.expandable.options",
    code: '<ExpandableText expanded={expanded} lines={2} className="text-sm leading-6">{description}</ExpandableText>' },
  { title: "controls.imageViewport.title", files: ["image-viewport"], Preview: ImageViewports,
    description: "controls.imageViewport.description", options: "controls.imageViewport.options",
    code: '<div className="flex h-80 flex-col"><ImageViewport src={url} alt={label} className="flex-1" /></div>' },
  { title: "controls.streaming.title", files: ["streaming-label-sheen"], Preview: StreamingLabels,
    description: "controls.streaming.description", options: "controls.streaming.options",
    code: '<StreamingLabelSheen active={running}>Working…</StreamingLabelSheen>' },
].map((example) => ({ ...example, files: example.files.map((file) => `${base}${file}.tsx`) }));
