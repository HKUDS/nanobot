import { render, waitFor } from "@testing-library/react";
import { expect, it } from "vitest";

import { MarkdownText } from "@/components/MarkdownText";
import mixedMathFixture from "@/tests/fixtures/markdown-math-mixed.md?raw";

const mixedMath = mixedMathFixture.replaceAll("\r\n", "\n");

it("retains a rendered TeX formula when an assistant response completes in streaming layout", async () => {
  const source = String.raw`Before

\[
\tan\left(\frac{\mathrm{HFOV}}{2}\right)
=
\frac{W}{2f_x}

\]

After`;
  const { container, rerender } = render(
    <MarkdownText streaming preserveStreamingLayout>{source}</MarkdownText>,
  );
  await waitFor(() => expect(container.querySelector(".katex-display")).toBeInTheDocument(), {
    timeout: 10_000,
  });
  const formula = container.querySelector(".katex-display");
  const tex = container.querySelector("annotation")?.textContent;

  rerender(<MarkdownText preserveStreamingLayout>{source}</MarkdownText>);
  await waitFor(() => expect(container.querySelector(".katex-display")).toBe(formula));
  expect(container.querySelector("annotation")?.textContent).toBe(tex);
  expect(container.querySelector(".katex-error")).toBeNull();
  expect(container.querySelector("h1, h2")).toBeNull();
  expect(container).toHaveTextContent("Before");
  expect(container).toHaveTextContent("After");
});

it("renders a mixed math response through streaming prefixes and completion", async () => {
  const { container, rerender } = render(
    <MarkdownText streaming preserveStreamingLayout>{""}</MarkdownText>,
  );
  // Load the lazy renderer before exercising updates through its error boundary.
  rerender(<MarkdownText streaming preserveStreamingLayout>{"# Ready"}</MarkdownText>);
  await waitFor(() => expect(container.querySelector("h1")).toHaveTextContent("Ready"), {
    timeout: 10_000,
  });

  const commandInList = String.raw`\[
x=1
\]

- \(\alpha+\beta=\gamma\)`;
  for (let end = 1; end <= commandInList.length; end++) {
    rerender(
      <MarkdownText streaming preserveStreamingLayout>{commandInList.slice(0, end)}</MarkdownText>,
    );
  }
  expect(container.querySelectorAll(".katex")).toHaveLength(2);

  rerender(<MarkdownText streaming preserveStreamingLayout>{mixedMath}</MarkdownText>);
  expect(container.querySelectorAll("h1")).toHaveLength(20);
  expect(container.querySelectorAll(".katex")).toHaveLength(34);
  expect(container.querySelector(".katex-error")).toBeNull();

  rerender(<MarkdownText preserveStreamingLayout>{mixedMath}</MarkdownText>);
  expect(container.querySelectorAll("h1")).toHaveLength(20);
  expect(container.querySelectorAll(".katex")).toHaveLength(34);
  expect(container.querySelector(".katex-error")).toBeNull();
  expect(container.querySelectorAll("table")).toHaveLength(1);
  expect(container.querySelector("blockquote")).toBeInTheDocument();
}, 30_000);
