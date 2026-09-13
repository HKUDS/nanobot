import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, ClipboardEvent, KeyboardEvent, RefObject } from "react";

import type { CapabilityMentionSegment } from "@/components/CliAppMentionText";
import { composerCompositionSegments, composerMentionText, editComposerMentionText, mentionTextOffset } from "@/lib/composer-mention-text";

type Snapshot = { value: string; start: number; end: number };
const HISTORY_LIMIT = 100;

export function useComposerMentionInput({
  segments,
  inputRef,
  onEdit,
  resetKey,
}: {
  segments: CapabilityMentionSegment[];
  inputRef: RefObject<HTMLTextAreaElement>;
  onEdit: (value: string, cursor: number) => void;
  resetKey?: string | null;
}) {
  const text = useMemo(() => composerMentionText(segments), [segments]);
  const textRef = useRef(text);
  const pendingSelection = useRef<{ start: number; end: number } | null>(null);
  const history = useRef<{ undo: Snapshot[]; redo: Snapshot[] }>({ undo: [], redo: [] });
  const lastEdit = useRef({ type: "", at: 0, cursor: -1 });
  const composing = useRef(false);
  const [compositionValue, setCompositionValue] = useState<string | null>(null);
  const compositionStart = useRef(text);
  const compositionSegments = useRef(segments);
  const compositionSelection = useRef<{ start: number; end: number }>();
  const lastSelection = useRef({ start: 0, end: 0 });
  const previousResetKey = useRef(resetKey);

  const rawSelection = useCallback(() => {
    const el = inputRef.current;
    const start = el?.selectionStart ?? textRef.current.display.length;
    const end = el?.selectionEnd ?? start;
    const selection = {
      start: mentionTextOffset(textRef.current, start, "toRaw", start === end ? "nearest" : "start"),
      end: mentionTextOffset(textRef.current, end, "toRaw", start === end ? "nearest" : "end"),
    };
    lastSelection.current = selection;
    return selection;
  }, [inputRef]);

  const selectRaw = useCallback((start: number, end = start) => {
    inputRef.current?.setSelectionRange(
      mentionTextOffset(textRef.current, start, "toDisplay", "start"),
      mentionTextOffset(textRef.current, end, "toDisplay", "end"),
    );
    lastSelection.current = { start, end };
  }, [inputRef]);

  useLayoutEffect(() => {
    if (previousResetKey.current !== resetKey) {
      previousResetKey.current = resetKey;
      history.current = { undo: [], redo: [] };
      pendingSelection.current = null;
      composing.current = false;
      setCompositionValue(null);
      lastEdit.current.type = "";
    }
    // Keep picker insertion undoable, but never restore a sent draft or another session's text.
    if (text.raw !== textRef.current.raw && !pendingSelection.current) {
      if (!text.raw) history.current = { undo: [], redo: [] };
      else {
        history.current.undo.push({ value: textRef.current.raw, ...lastSelection.current });
        if (history.current.undo.length > HISTORY_LIMIT) history.current.undo.shift();
        history.current.redo = [];
      }
      lastEdit.current.type = "";
    }
    textRef.current = text;
    if (!composing.current && pendingSelection.current) {
      const { start, end } = pendingSelection.current;
      selectRaw(start, end);
      pendingSelection.current = null;
    }
  });

  const apply = useCallback((value: string, cursor: number, type = "", selection = rawSelection()) => {
    const previous = textRef.current;
    if (value !== previous.raw) {
      const now = Date.now();
      const coalesce = type && type === lastEdit.current.type && now - lastEdit.current.at < 750
        && selection.start === selection.end && selection.start === lastEdit.current.cursor;
      if (!coalesce) {
        history.current.undo.push({ value: previous.raw, ...selection });
        if (history.current.undo.length > HISTORY_LIMIT) history.current.undo.shift();
      }
      history.current.redo = [];
      lastEdit.current = { type, at: now, cursor };
    }
    pendingSelection.current = value === previous.raw ? null : { start: cursor, end: cursor };
    onEdit(value, cursor);
  }, [onEdit, rawSelection]);

  const beforeSelection = useRef<{ start: number; end: number; raw: { start: number; end: number } } | null>(null);
  const captureSelection = useCallback(() => {
    const el = inputRef.current;
    if (el) beforeSelection.current = { start: el.selectionStart, end: el.selectionEnd, raw: rawSelection() };
  }, [inputRef, rawSelection]);
  const onChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    if (composing.current || (event.nativeEvent as InputEvent).isComposing) {
      if (!composing.current && compositionValue === null) {
        compositionSegments.current = segments;
        compositionSelection.current = beforeSelection.current ?? undefined;
      }
      setCompositionValue(event.target.value);
      return;
    }
    setCompositionValue(null);
    const edited = editComposerMentionText(textRef.current, event.target.value, event.target.selectionStart,
      beforeSelection.current ?? undefined);
    apply(edited.value, edited.cursor, (event.nativeEvent as InputEvent).inputType,
      beforeSelection.current?.raw);
    beforeSelection.current = null;
  };

  const undo = useCallback((redo: boolean) => {
    const from = redo ? history.current.redo : history.current.undo;
    const to = redo ? history.current.undo : history.current.redo;
    const snapshot = from.pop();
    if (!snapshot) return;
    to.push({ value: textRef.current.raw, ...rawSelection() });
    pendingSelection.current = snapshot;
    lastEdit.current.type = "";
    onEdit(snapshot.value, snapshot.start);
  }, [onEdit, rawSelection]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    const beforeInput = (event: InputEvent) => {
      if (event.inputType === "historyUndo" || event.inputType === "historyRedo") {
        event.preventDefault();
        undo(event.inputType === "historyRedo");
      } else {
        captureSelection();
      }
    };
    el.addEventListener("beforeinput", beforeInput);
    return () => el.removeEventListener("beforeinput", beforeInput);
  }, [captureSelection, inputRef, undo]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (composing.current || event.nativeEvent.isComposing) return;
    const key = event.key.toLowerCase();
    if ((event.metaKey || event.ctrlKey) && !event.altKey && (key === "z" || key === "y")) {
      event.preventDefault();
      undo(key === "y" || event.shiftKey);
    }
    captureSelection();
  };

  const copy = (event: ClipboardEvent<HTMLTextAreaElement>, cut: boolean) => {
    const selection = rawSelection();
    if (selection.start === selection.end) return;
    event.preventDefault();
    event.clipboardData.setData("text/plain", textRef.current.raw.slice(selection.start, selection.end));
    if (cut) apply(textRef.current.raw.slice(0, selection.start) + textRef.current.raw.slice(selection.end), selection.start);
  };

  return {
    value: compositionValue ?? text.display,
    segments: compositionValue === null ? segments : composerCompositionSegments(
      compositionSegments.current, compositionValue, compositionSelection.current,
    ),
    isComposing: compositionValue !== null,
    rawSelection,
    replace: apply,
    onChange,
    onKeyDown,
    onCopy: (event: ClipboardEvent<HTMLTextAreaElement>) => copy(event, false),
    onCut: (event: ClipboardEvent<HTMLTextAreaElement>) => copy(event, true),
    onCompositionStart: () => {
      composing.current = true;
      compositionStart.current = textRef.current;
      compositionSegments.current = segments;
      const el = inputRef.current;
      compositionSelection.current = el ? { start: el.selectionStart, end: el.selectionEnd } : undefined;
      setCompositionValue(inputRef.current?.value ?? textRef.current.display);
    },
    onCompositionEnd: () => {
      if (!composing.current) return;
      const el = inputRef.current;
      composing.current = false;
      setCompositionValue(null);
      if (!el) return;
      const edited = editComposerMentionText(compositionStart.current, el.value, el.selectionStart, compositionSelection.current);
      apply(edited.value, edited.cursor);
      beforeSelection.current = null;
    },
  };
}
