import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilePreviewAvailabilityProvider } from "@/components/FilePreviewAvailabilityContext";
import MarkdownTextRenderer from "@/components/MarkdownTextRenderer";

describe("MarkdownTextRenderer", () => {
  it("renders clickable markdown links in blue", () => {
    render(<MarkdownTextRenderer>[local server](http://127.0.0.1:7891/)</MarkdownTextRenderer>);

    const link = screen.getByRole("link", { name: "local server" });
    expect(link).toHaveAttribute("href", "http://127.0.0.1:7891/");
    expect(link).toHaveClass("text-blue-500", "dark:text-blue-300");
  });

  it("does not render active URL protocols from untrusted markdown", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {[
          "[JavaScript](javascript:alert(1))",
          "[Data](data:text/html,<script>alert(1)</script>)",
          "![Unsafe image](javascript:alert(2))",
        ].join(" ")}
      </MarkdownTextRenderer>,
    );

    expect(container).toHaveTextContent("JavaScript Data");
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("keeps safe external, mail, relative, and fragment links", () => {
    render(
      <MarkdownTextRenderer>
        {[
          "[HTTPS](https://example.com)",
          "[Mail](mailto:hello@example.com)",
          "[Relative](/docs/getting-started)",
          "[Fragment](#install)",
        ].join(" ")}
      </MarkdownTextRenderer>,
    );

    expect(screen.getByRole("link", { name: "HTTPS" })).toHaveAttribute(
      "href",
      "https://example.com",
    );
    expect(screen.getByRole("link", { name: "Mail" })).toHaveAttribute(
      "href",
      "mailto:hello@example.com",
    );
    expect(screen.getByRole("link", { name: "Relative" })).toHaveAttribute(
      "href",
      "/docs/getting-started",
    );
    expect(screen.getByRole("link", { name: "Fragment" })).toHaveAttribute(
      "href",
      "#install",
    );
  });

  it("renders local file links as previewable file references", () => {
    const onOpenFilePreview = vi.fn();
    render(
      <MarkdownTextRenderer onOpenFilePreview={onOpenFilePreview}>
        {"Edited [hook.py](/Users/test/project/nanobot/agent/hook.py:12)"}
      </MarkdownTextRenderer>,
    );

    const reference = screen.getByTestId("inline-file-path");
    expect(reference).toHaveTextContent("hook.py");
    expect(reference).toHaveAttribute(
      "aria-label",
      "/Users/test/project/nanobot/agent/hook.py",
    );

    fireEvent.click(reference);

    expect(onOpenFilePreview).toHaveBeenCalledWith(
      "/Users/test/project/nanobot/agent/hook.py",
    );
  });

  it("keeps unavailable inferred inline file paths non-interactive", async () => {
    const onOpenFilePreview = vi.fn();
    const resolve = vi.fn().mockResolvedValue(false);
    render(
      <FilePreviewAvailabilityProvider resolve={resolve}>
        <MarkdownTextRenderer onOpenFilePreview={onOpenFilePreview}>
          {"Future file: `notes/missing.md`"}
        </MarkdownTextRenderer>
      </FilePreviewAvailabilityProvider>,
    );

    const reference = screen.getByTestId("inline-file-path");
    expect(reference).toHaveTextContent("missing.md");
    await waitFor(() => expect(resolve).toHaveBeenCalledWith("notes/missing.md"));
    expect(reference).not.toHaveAttribute("role");
    expect(reference).not.toHaveAttribute("tabindex");

    fireEvent.click(reference);

    expect(onOpenFilePreview).not.toHaveBeenCalled();
  });

  it("keeps inferred inline file paths non-interactive when availability lookup fails", async () => {
    const onOpenFilePreview = vi.fn();
    let rejectAvailability!: (reason?: unknown) => void;
    const resolve = vi.fn(() => new Promise<boolean>((_resolve, reject) => {
      rejectAvailability = reject;
    }));
    render(
      <FilePreviewAvailabilityProvider resolve={resolve}>
        <MarkdownTextRenderer onOpenFilePreview={onOpenFilePreview}>
          {"Unreadable file: `notes/locked.md`"}
        </MarkdownTextRenderer>
      </FilePreviewAvailabilityProvider>,
    );

    const reference = screen.getByTestId("inline-file-path");
    await waitFor(() => expect(resolve).toHaveBeenCalledWith("notes/locked.md"));
    await act(async () => {
      rejectAvailability(new Error("probe failed"));
      await Promise.resolve();
    });

    expect(reference).not.toHaveAttribute("role");
    expect(reference).not.toHaveAttribute("tabindex");
    fireEvent.click(reference);
    expect(onOpenFilePreview).not.toHaveBeenCalled();
  });

  it("makes available inferred inline file paths previewable", async () => {
    const onOpenFilePreview = vi.fn();
    const resolve = vi.fn().mockResolvedValue(true);
    render(
      <FilePreviewAvailabilityProvider resolve={resolve}>
        <MarkdownTextRenderer onOpenFilePreview={onOpenFilePreview}>
          {"Existing file: `notes/ready.md`"}
        </MarkdownTextRenderer>
      </FilePreviewAvailabilityProvider>,
    );

    const reference = screen.getByTestId("inline-file-path");
    await waitFor(() => expect(reference).toHaveAttribute("role", "button"));
    expect(reference).toHaveAttribute("tabindex", "0");

    fireEvent.click(reference);

    expect(onOpenFilePreview).toHaveBeenCalledWith("notes/ready.md");
  });

  it("does not treat non-file hrefs as previews just because the label looks like a file", () => {
    const onOpenFilePreview = vi.fn();
    render(
      <MarkdownTextRenderer onOpenFilePreview={onOpenFilePreview}>
        {"Download [index.html](/api/media/sig/html)"}
      </MarkdownTextRenderer>,
    );

    expect(screen.queryByTestId("inline-file-path")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "index.html" })).toHaveAttribute(
      "href",
      "/api/media/sig/html",
    );
  });

  it("renders glob file links as plain text instead of preview targets", () => {
    const onOpenFilePreview = vi.fn();
    const { container } = render(
      <MarkdownTextRenderer onOpenFilePreview={onOpenFilePreview}>
        {"原始对话通常还在 [*.json](*.json)。"}
      </MarkdownTextRenderer>,
    );

    expect(screen.queryByTestId("inline-file-path")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "*.json" })).not.toBeInTheDocument();
    expect(container).toHaveTextContent("*.json");
  });

  it("keeps glob inline code as code instead of a file preview chip", () => {
    render(
      <MarkdownTextRenderer>
        {"检查 `src/**/*.json`。"}
      </MarkdownTextRenderer>,
    );

    expect(screen.queryByTestId("inline-file-path")).not.toBeInTheDocument();
    expect(screen.getByText("src/**/*.json").tagName).toBe("CODE");
  });

  it("does not wrap complete fenced code blocks in an extra pre", () => {
    const { container } = render(
      <MarkdownTextRenderer highlightCode={false}>
        {"当前目录:\n\n```text\n/Users/renxubin/.nanobot/workspace\n```"}
      </MarkdownTextRenderer>,
    );

    expect(screen.getByText("/Users/renxubin/.nanobot/workspace")).toBeInTheDocument();
    expect(container.querySelectorAll("pre")).toHaveLength(1);
    expect(container.querySelector("pre div")).toBeNull();
  });

  it("renders bare fenced code blocks without crashing", () => {
    const { container } = render(
      <MarkdownTextRenderer highlightCode={false}>
        {"Some text\n\n```\ncode without language\n```"}
      </MarkdownTextRenderer>,
    );

    expect(screen.getByText("code without language")).toBeInTheDocument();
    expect(screen.queryByText("text")).not.toBeInTheDocument();
    expect(container.querySelector(".not-prose")).toHaveAttribute("data-language", "text");
    expect(container.querySelectorAll("pre")).toHaveLength(1);
  });

  it("keeps streaming unfinished fenced code blocks to a single shell", () => {
    const { container } = render(
      <MarkdownTextRenderer highlightCode={false}>
        {"当前目录:\n\n```text\n/Users/renxubin/.nanobot/workspace"}
      </MarkdownTextRenderer>,
    );

    expect(screen.getByText("/Users/renxubin/.nanobot/workspace")).toBeInTheDocument();
    expect(container.querySelectorAll("pre")).toHaveLength(1);
    expect(container.querySelector("pre div")).toBeNull();
  });

  it("renders markdown images as inline previews", () => {
    render(<MarkdownTextRenderer>![Diagram](/api/media/sig/payload)</MarkdownTextRenderer>);

    const image = screen.getByRole("img", { name: "Diagram" });
    expect(image).toHaveAttribute("src", "/api/media/sig/payload");
    expect(screen.getByRole("link", { name: "Open Diagram" })).toHaveAttribute(
      "href",
      "/api/media/sig/payload",
    );
  });

  it("renders markdown videos as inline players", () => {
    render(<MarkdownTextRenderer>![nanobot-intro.mp4](/api/media/sig/video)</MarkdownTextRenderer>);

    const video = screen.getByLabelText("Video attachment: nanobot-intro.mp4");
    expect(video.tagName).toBe("VIDEO");
    expect(video).toHaveAttribute("src", "/api/media/sig/video");
    expect(video).toHaveAttribute("controls");
    expect(screen.queryByRole("img", { name: "nanobot-intro.mp4" })).not.toBeInTheDocument();
  });

  it("renders markdown links with file-looking names as file attachments", () => {
    render(<MarkdownTextRenderer>![index.html](/api/media/sig/html)</MarkdownTextRenderer>);

    expect(screen.getByLabelText("File attachment")).toHaveTextContent("index.html");
    expect(screen.queryByRole("img", { name: "index.html" })).not.toBeInTheDocument();
  });

  it("renders title plus url list items as compact link rows", () => {
    render(
      <MarkdownTextRenderer>
        {
          "Sources:\n\n- Polymarket — “When will GPT-5.6 be released?”\n  https://polymarket.com/event/when-will-gpt-5pt6-be-released\n- Polymarket — “GPT-5.6 released by...?”\n  https://polymarket.com/event/gpt-5pt6-released-by"
        }
      </MarkdownTextRenderer>,
    );

    expect(
      screen.getByRole("link", {
        name: "Open link: Polymarket — When will GPT-5.6 be released?",
      }),
    ).toHaveAttribute(
      "href",
      "https://polymarket.com/event/when-will-gpt-5pt6-be-released",
    );
    expect(
      screen.getByRole("link", {
        name: "Open link: Polymarket — GPT-5.6 released by...?",
      }),
    ).toHaveAttribute("href", "https://polymarket.com/event/gpt-5pt6-released-by");
    expect(screen.queryByText("Polymarket · polymarket.com")).not.toBeInTheDocument();
  });

  it("does not require a source heading for compact link rows", () => {
    render(
      <MarkdownTextRenderer>
        {
          "Useful links:\n\n- Polymarket — “When will GPT-5.6 be released?”\n  https://polymarket.com/event/when-will-gpt-5pt6-be-released"
        }
      </MarkdownTextRenderer>,
    );

    expect(
      screen.getByRole("link", {
        name: "Open link: Polymarket — When will GPT-5.6 be released?",
      }),
    ).toHaveAttribute("href", "https://polymarket.com/event/when-will-gpt-5pt6-be-released");
  });

  it("falls back through favicon sources before showing a globe for compact link rows", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {
          "Useful links:\n\n- Savills Hong Kong Corporate Relocation — Corporate relocation services\n  https://www.savills.com.hk/services/corporate-relocation.aspx"
        }
      </MarkdownTextRenderer>,
    );
    const link = screen.getByRole("link", {
      name: "Open link: Savills Hong Kong Corporate Relocation — Corporate relocation services",
    });
    const favicon = () => link.querySelector("img");

    expect(favicon()).toHaveAttribute(
      "src",
      "https://favicon.im/www.savills.com.hk?larger=true",
    );

    fireEvent.error(favicon()!);
    expect(favicon()).toHaveAttribute(
      "src",
      "https://www.google.com/s2/favicons?domain=www.savills.com.hk&sz=64",
    );

    fireEvent.error(favicon()!);
    expect(favicon()).toHaveAttribute(
      "src",
      "https://icons.duckduckgo.com/ip3/www.savills.com.hk.ico",
    );

    fireEvent.error(favicon()!);
    expect(favicon()).toHaveAttribute(
      "src",
      "https://www.savills.com.hk/favicon.ico",
    );

    fireEvent.error(favicon()!);
    expect(favicon()).not.toBeInTheDocument();
    expect(link.querySelector("svg")).toBeInTheDocument();
    expect(container).not.toHaveTextContent("SC");
  });

  it("renders media attachments without an extra preview/code wrapper", () => {
    render(<MarkdownTextRenderer>![Diagram](/api/media/sig/payload)</MarkdownTextRenderer>);

    expect(screen.getByRole("img", { name: "Diagram" })).toHaveAttribute(
      "src",
      "/api/media/sig/payload",
    );
    expect(screen.getByRole("link", { name: "Open Diagram" })).toHaveAttribute(
      "href",
      "/api/media/sig/payload",
    );
    expect(screen.queryByRole("button", { name: "Code" })).not.toBeInTheDocument();
  });

  it("renders a safe subset of inline HTML", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {"<mark>高亮文本</mark>\n\n上标：x<sup>2</sup>\n下标：H<sub>2</sub>O"}
      </MarkdownTextRenderer>,
    );

    expect(container.querySelector("mark")).toHaveTextContent("高亮文本");
    expect(container.querySelector("sup")).toHaveTextContent("2");
    expect(container.querySelector("sub")).toHaveTextContent("2");
  });

  it("keeps unsafe HTML as text", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {"<script>alert(1)</script>\n\n<mark onclick=\"alert(1)\">bad</mark>"}
      </MarkdownTextRenderer>,
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("mark")).toBeNull();
    expect(container).toHaveTextContent("<script>alert(1)</script>");
    expect(container).toHaveTextContent("<mark onclick=\"alert(1)\">bad</mark>");
  });

  it("renders safe details blocks", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {
          "<details><summary>点击展开更多内容</summary>\n\n这里是被折叠的内容。\n\n- 可以放列表\n\n</details>"
        }
      </MarkdownTextRenderer>,
    );

    expect(container.querySelector("details")).toBeInTheDocument();
    expect(container.querySelector("summary")).toHaveTextContent("点击展开更多内容");
    expect(screen.getByText("这里是被折叠的内容。")).toBeInTheDocument();
    expect(screen.getByText("可以放列表")).toBeInTheDocument();
    expect(container).not.toHaveTextContent("</details>");
  });

  it("renders task lists with compact static status markers", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {"- [x] 写 Markdown 示例\n- [x] 加点 emoji\n- [ ] 测试渲染效果"}
      </MarkdownTextRenderer>,
    );

    expect(container.querySelectorAll("input[type='checkbox']")).toHaveLength(0);
    expect(screen.getAllByTestId("markdown-task-checkbox")).toHaveLength(3);
    expect(container.querySelectorAll(".task-list-item")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /tasks/i })).not.toBeInTheDocument();
  });

  it("renders GFM tables in a responsive data surface", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {
          "## Models\n\n| Model | Context | Price |\n| --- | ---: | ---: |\n| nanobot | 200k | $1 |\n\n## Notes"
        }
      </MarkdownTextRenderer>,
    );

    const surface = screen.getByTestId("markdown-data-table");
    expect(surface).toHaveClass("overflow-x-auto", "rounded-lg", "mb-5");
    expect(surface).toHaveAttribute("role", "region");
    expect(surface).toHaveAttribute("tabindex", "0");
    expect(surface).toHaveAccessibleName("Data table");
    expect(screen.getByRole("table")).toHaveTextContent("nanobot");
    expect(container.firstElementChild).toHaveClass("space-y-4");
    expect(container.firstElementChild).not.toHaveClass("space-y-0");
  });

  it("uses Streamdown's incremental reveal while content is streaming", () => {
    const { container } = render(
      <MarkdownTextRenderer streaming>春天</MarkdownTextRenderer>,
    );

    expect(container.firstElementChild).toHaveClass(
      "[&>*:last-child]:after:content-[var(--streamdown-caret)]",
    );
    const animatedUnits = container.querySelectorAll<HTMLElement>("[data-sd-animate]");
    expect(animatedUnits).toHaveLength(1);
    expect(animatedUnits[0]).toHaveTextContent("春天");
    expect(animatedUnits[0].getAttribute("style")).toContain("--sd-duration: 180ms");
  });

  it("removes animation markup when a streamed response completes", async () => {
    const { container, rerender } = render(
      <MarkdownTextRenderer streaming>春天</MarkdownTextRenderer>,
    );
    expect(container.querySelector("[data-sd-animate]")).toBeInTheDocument();

    rerender(<MarkdownTextRenderer>春天</MarkdownTextRenderer>);

    await waitFor(() => {
      expect(container.querySelector("[data-sd-animate]")).not.toBeInTheDocument();
    });
  });

  it("does not create one DOM node per CJK character for long responses", () => {
    const { container } = render(
      <MarkdownTextRenderer streaming>{"长".repeat(6_001)}</MarkdownTextRenderer>,
    );

    expect(container.querySelectorAll("[data-sd-animate]")).toHaveLength(1);
    expect(container.querySelector("[data-nanobot-stream-unit]")).not.toBeInTheDocument();
  });

  it("repairs incomplete streaming markdown without exposing syntax fragments", () => {
    const { container, rerender } = render(
      <MarkdownTextRenderer streaming>{"**partial answer"}</MarkdownTextRenderer>,
    );

    expect(container).toHaveTextContent("partial answer");
    expect(container).not.toHaveTextContent("**partial answer");

    rerender(
      <MarkdownTextRenderer streaming>
        {"[OpenAI](https://openai.com"}
      </MarkdownTextRenderer>,
    );
    expect(screen.queryByRole("link", { name: "OpenAI" })).not.toBeInTheDocument();
    expect(container).toHaveTextContent("OpenAI");

    rerender(
      <MarkdownTextRenderer streaming>
        {"[OpenAI](https://openai.com)"}
      </MarkdownTextRenderer>,
    );
    expect(screen.getByRole("link", { name: "OpenAI" })).toHaveAttribute(
      "href",
      "https://openai.com",
    );

    rerender(
      <MarkdownTextRenderer streaming highlightCode={false}>
        {"```ts\nconst value = 1;"}
      </MarkdownTextRenderer>,
    );
    expect(screen.getByText("const value = 1;")).toBeInTheDocument();
  });

  it("preserves semantic emphasis without leaking parser metadata into the DOM", () => {
    render(
      <MarkdownTextRenderer>
        {"**Important** and *careful* with [links](https://example.com)."}
      </MarkdownTextRenderer>,
    );

    expect(screen.getByText("Important").tagName).toBe("STRONG");
    expect(screen.getByText("careful").tagName).toBe("EM");
    expect(screen.getByRole("link", { name: "links" })).not.toHaveAttribute("node");
  });

  it("adds line numbers to multiline fenced code without changing inline code", () => {
    render(
      <MarkdownTextRenderer highlightCode={false}>
        {"```ts\nconst one = 1;\nconst two = 2;\n```\n\nUse `one` next."}
      </MarkdownTextRenderer>,
    );

    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("one").tagName).toBe("CODE");
  });

  it("keeps dollar amounts from being parsed as inline math", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {
          "VBeats mentions $24 million, while Globe states a total of $130.6 million since founding."
        }
      </MarkdownTextRenderer>,
    );

    expect(container).toHaveTextContent(
      "VBeats mentions $24 million, while Globe states a total of $130.6 million since founding.",
    );
    expect(container.querySelector(".katex")).toBeNull();
  });

  it("renders guarded single-dollar inline math", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {
          "Variables $x$ and powers $2^n$ render inline, while a price range $10-20$ stays literal."
        }
      </MarkdownTextRenderer>,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(2);
    expect(container).not.toHaveTextContent("$x$");
    expect(container).not.toHaveTextContent("$2^n$");
    expect(container).toHaveTextContent("$10-20$");
  });

  it("renders model-style single-dollar formula lists", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {[
          "- Fourier transform: $\\hat{f}(\\xi) = \\int_{-\\infty}^{+\\infty} f(x)e^{-2\\pi i x \\xi}\\, dx$",
          "- Taylor expansion: $e^x = \\sum_{n=0}^{\\infty} \\frac{x^n}{n!}$",
          "- KL divergence: $D_\\text{KL}(P || Q) = \\sum_x P(x) \\log \\frac{P(x)}{Q(x)}$",
          "- Quantum state: $\\psi = \\alpha|0\\rangle + \\beta|1\\rangle$",
        ].join("\n")}
      </MarkdownTextRenderer>,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(4);
    expect(container).not.toHaveTextContent("$\\hat{f}");
    expect(container).not.toHaveTextContent("$D_\\text");
  });

  it("renders TeX inline math delimiters", () => {
    const { container } = render(
      <MarkdownTextRenderer>{"Einstein wrote \\(E = mc^2\\) for mass-energy equivalence."}</MarkdownTextRenderer>,
    );

    expect(container.querySelector(".katex")).toBeInTheDocument();
    expect(container.querySelector(".katex-display")).toBeNull();
    expect(container).not.toHaveTextContent("\\(");
    expect(container).not.toHaveTextContent("\\)");
  });

  it("renders TeX display math delimiters", () => {
    const { container } = render(
      <MarkdownTextRenderer>{"\\[x^2 + y^2 = z^2\\]"}</MarkdownTextRenderer>,
    );

    expect(container.querySelector(".katex-display")).toBeInTheDocument();
    expect(container).not.toHaveTextContent("\\[");
    expect(container).not.toHaveTextContent("\\]");
  });

  it("keeps TeX delimiters inside code literal", () => {
    const { container } = render(
      <MarkdownTextRenderer highlightCode={false}>
        {"Inline `\\(x\\)` stays literal.\n\n```text\n\\[x^2\\]\n```"}
      </MarkdownTextRenderer>,
    );

    expect(container.querySelector(".katex")).toBeNull();
    expect(screen.getByText("\\(x\\)").tagName).toBe("CODE");
    expect(screen.getByText("\\[x^2\\]")).toBeInTheDocument();
  });

  it("still renders explicit math blocks", () => {
    const { container } = render(
      <MarkdownTextRenderer>{"$$x^2 + y^2 = z^2$$"}</MarkdownTextRenderer>,
    );

    expect(container.querySelector(".katex")).toBeInTheDocument();
  });
});
