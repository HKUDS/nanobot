import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MarkdownTextRenderer from "@/components/MarkdownTextRenderer";

describe("MarkdownTextRenderer", () => {
  it("renders clickable markdown links in blue", () => {
    render(<MarkdownTextRenderer>[local server](http://127.0.0.1:7891/)</MarkdownTextRenderer>);

    const link = screen.getByRole("link", { name: "local server" });
    expect(link).toHaveAttribute("href", "http://127.0.0.1:7891/");
    expect(link).toHaveClass("text-blue-500", "dark:text-blue-300");
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
    expect(screen.getByText("text")).toBeInTheDocument();
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

  it("renders task list checkboxes as quiet status marks", () => {
    const { container } = render(
      <MarkdownTextRenderer>
        {"- [x] 写 Markdown 示例\n- [x] 加点 emoji\n- [ ] 测试渲染效果"}
      </MarkdownTextRenderer>,
    );

    expect(container.querySelectorAll("input[type='checkbox']")).toHaveLength(0);
    expect(screen.getAllByTestId("markdown-task-checkbox")).toHaveLength(3);
    expect(container.querySelectorAll(".task-list-item")).toHaveLength(3);
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

  it("still renders explicit math blocks", () => {
    const { container } = render(
      <MarkdownTextRenderer>{"$$x^2 + y^2 = z^2$$"}</MarkdownTextRenderer>,
    );

    expect(container.querySelector(".katex")).toBeInTheDocument();
  });
});
