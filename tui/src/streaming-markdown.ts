import {
  MarkdownRenderable,
  TextRenderable,
  type ColorInput,
  type MarkdownOptions,
  type RenderContext,
  type RGBA,
} from "@opentui/core"

function isPlainText(content: string): boolean {
  return /^[\p{L}\p{N}][\p{L}\p{N}\p{Zs},.!?;'"，。！？、；：“”‘’（）$^+=()\n-]*$/u.test(content)
    && !/\n[^\p{L}\p{N}\n]/u.test(content)
    && !/\n{3}/u.test(content)
    && !/^\d+[.)](?: |$)/mu.test(content)
    && !/\bwww\./iu.test(content)
}

/** Keeps unformatted paragraphs on a retained text node until Markdown is needed. */
export class StreamingMarkdownRenderable extends MarkdownRenderable {
  private plainText: TextRenderable | null = null
  private plainContent: string | null = null

  constructor(context: RenderContext, options: MarkdownOptions) {
    super(context, { ...options, content: "" })
    this.content = options.content ?? ""
  }

  override get content(): string {
    return this.plainContent ?? super.content
  }

  override set content(value: string) {
    if (this.isDestroyed) return
    // Once Markdown has appeared, keep its retained blocks and parser state.
    if ((super.streaming || this.plainText) && !super.content && isPlainText(value)) {
      const displayed = value.replace(/\n+$/u, "")
      if (!this.plainText) {
        this.plainText = new TextRenderable(this.ctx, {
          id: this.id + "-plain",
          width: "100%",
          wrapMode: "word",
          fg: this.fg,
          content: displayed,
        })
        this.add(this.plainText)
      } else {
        this.plainText.content = displayed
      }
      this.plainContent = value
      return
    }
    this.clearPlainText()
    super.content = value
  }

  override get fg(): RGBA | undefined {
    return super.fg
  }

  override set fg(value: ColorInput | undefined) {
    super.fg = value
    if (this.plainText) this.plainText.fg = value
  }

  private clearPlainText(): void {
    if (this.plainText) {
      this.remove(this.plainText)
      this.plainText.destroyRecursively()
      this.plainText = null
    }
    this.plainContent = null
  }
}
