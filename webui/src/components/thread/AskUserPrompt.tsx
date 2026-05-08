import { useCallback, useEffect, useRef, useState } from "react";
import { MessageSquareText } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface AskUserPromptProps {
  question: string;
  buttons: string[][];
  onAnswer: (answer: string) => void;
}

export function AskUserPrompt({
  question,
  buttons,
  onAnswer,
}: AskUserPromptProps) {
  const [customOpen, setCustomOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const options = buttons.flat().filter(Boolean);

  useEffect(() => {
    if (customOpen) {
      inputRef.current?.focus();
    }
  }, [customOpen]);

  const submitCustom = useCallback(() => {
    const answer = custom.trim();
    if (!answer) return;
    onAnswer(answer);
    setCustom("");
    setCustomOpen(false);
  }, [custom, onAnswer]);

  if (options.length === 0) return null;

  return (
    <div
      className={cn(
        "mx-auto mb-2 w-full max-w-[49.5rem] rounded-[16px] border border-primary/30",
        "bg-card/95 p-3 shadow-sm backdrop-blur",
      )}
      role="group"
      aria-label="Question"
    >
      <div className="mb-2 flex items-start gap-2">
        <div className="mt-0.5 rounded-full bg-primary/10 p-1.5 text-primary">
          <MessageSquareText className="h-3.5 w-3.5" aria-hidden />
        </div>
        <p className="min-w-0 flex-1 text-[13.5px] font-medium leading-5 text-foreground">
          {question}
        </p>
      </div>

      <div className="grid gap-1.5 sm:grid-cols-2">
        {options.map((option) => (
          <Button
            key={option}
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onAnswer(option)}
            className="justify-start rounded-[10px] px-3 text-left"
          >
            <span className="truncate">{option}</span>
          </Button>
        ))}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setCustomOpen((open) => !open)}
          className="justify-start rounded-[10px] px-3 text-muted-foreground"
        >
          Other...
        </Button>
      </div>

      {customOpen ? (
        <div className="mt-2 flex gap-2">
          <textarea
            ref={inputRef}
            value={custom}
            onChange={(event) => setCustom(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submitCustom();
              }
            }}
            rows={1}
            placeholder="Type your own answer..."
            className={cn(
              "min-h-9 flex-1 resize-none rounded-[10px] border border-border/70 bg-background",
              "px-3 py-2 text-[13.5px] leading-5 outline-none placeholder:text-muted-foreground",
              "focus-visible:ring-1 focus-visible:ring-primary/40",
            )}
          />
          <Button type="button" size="sm" onClick={submitCustom} disabled={!custom.trim()}>
            Send
          </Button>
        </div>
      ) : null}
    </div>
  );
}
