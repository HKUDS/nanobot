import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { WebLink, WebPreviewContext } from "@/components/WebLink";
import { useMessageWebLinks } from "@/components/MessageLinksMenu";
import { copyTextToClipboard } from "@/lib/clipboard";

vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: vi.fn(async () => true) }));
afterEach(() => { cleanup(); vi.mocked(copyTextToClipboard).mockReset().mockResolvedValue(true); });

function view(content: string, openPreview?: (url: string) => void) {
  return <WebPreviewContext.Provider value={openPreview}>
    <ThreadMessages messages={[{ id: "links", role: "assistant", content, createdAt: 1 }]} />
  </WebPreviewContext.Provider>;
}

async function openLinks() {
  fireEvent.click(screen.getByRole("button", { name: "Message actions" }));
  fireEvent.click(await screen.findByRole("button", { name: "View links" }));
  return screen.getByRole("dialog", { name: "Message actions" });
}

describe("message link actions", () => {
  it("collects rendered links, deduplicates destinations and ignores code, images and file references", async () => {
    render(view("[First](https://example.com/) and [Again](https://example.com).\n\n[Second](https://example.org/demo)\n\nhttps://example.net/plain\n\n`https://code.invalid/inline`\n\n```text\nhttps://code.invalid/block\n```\n\n![Image](https://image.invalid/pic.png)\n\n[notes.txt](notes.txt)"));
    await screen.findByRole("link", { name: "First" });
    const menu = await openLinks();
    expect(within(menu).getAllByRole("button").map(button => button.textContent)).toEqual(["View links", "First", "Second", "https://example.net/plain"]);
    expect(within(menu).queryByRole("button", { name: "Again" })).not.toBeInTheDocument();
    expect(within(menu).getByRole("button", { name: "Second" })).toBeVisible();
    expect(within(menu).getByRole("button", { name: "https://example.net/plain" })).toBeVisible();
    fireEvent.click(within(menu).getByRole("button", { name: "First" }));
    expect(within(menu).getByRole("link", { name: "Open in browser" })).toHaveAttribute("href", "https://example.com/");
    expect(within(menu).getByRole("link", { name: "Open in browser" })).toHaveAttribute("rel", "noreferrer noopener");
    expect(within(menu).queryByRole("button", { name: "Preview website" })).not.toBeInTheDocument();
    fireEvent.click(within(menu).getByRole("button", { name: "Back" }));
    expect(within(menu).getByRole("button", { name: "Second" })).toBeVisible();
    fireEvent.click(within(menu).getByRole("button", { name: "Back" }));
    expect(within(menu).getByRole("button", { name: "View links" })).toBeVisible();
  });

  it("does not show an entry for a message without a rendered web link", async () => {
    render(view("No links here. `https://example.com/code` [Mail](mailto:test@example.com) [Unsafe](javascript:alert)"));
    await screen.findByText(/No links here/);
    fireEvent.click(screen.getByRole("button", { name: "Message actions" }));
    expect(screen.queryByRole("button", { name: "View links" })).not.toBeInTheDocument();
  });

  it("opens the single link's actions directly and closes the message menu on preview", async () => {
    const preview = vi.fn();
    render(view("[Website](https://example.com/demo?q=one#two)", preview));
    await screen.findByRole("link", { name: /Website/ });
    const menu = await openLinks();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(within(menu).getByRole("button", { name: "Preview website" }));
    expect(preview).toHaveBeenCalledWith("https://example.com/demo?q=one#two");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Message actions" }));
    expect(screen.getByRole("button", { name: "View links" })).toBeVisible();
  });

  it("provides copy feedback and retry without losing the selected link", async () => {
    vi.mocked(copyTextToClipboard).mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    render(view("[Website](https://example.com/demo)"));
    await screen.findByRole("link", { name: /Website/ });
    const menu = await openLinks();
    fireEvent.click(within(menu).getByRole("button", { name: "Copy link" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Could not copy link");
    fireEvent.click(within(menu).getByRole("button", { name: "Copy link" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Link copied"));
    expect(copyTextToClipboard).toHaveBeenLastCalledWith("https://example.com/demo");
    fireEvent.keyDown(menu, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Message actions" })).toHaveFocus();
  });

  it("ignores late copy feedback after going back", async () => {
    let finish!: (result: boolean) => void;
    vi.mocked(copyTextToClipboard).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    render(view("[Old](https://example.com/old)"));
    await screen.findByRole("link", { name: /Old/ });
    const menu = await openLinks();
    fireEvent.click(within(menu).getByRole("button", { name: "Copy link" }));
    fireEvent.click(within(menu).getByRole("button", { name: "Back" }));
    await act(async () => finish(true));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(within(menu).getByRole("button", { name: "View links" })).toBeVisible();
  });

  it("tracks newly rendered or changed links only within the owning message", async () => {
    function LiveMessage({ href }: { href: string | null }) {
      const root = useRef<HTMLDivElement>(null);
      const links = useMessageWebLinks(root, true);
      return <><WebLink href="https://elsewhere.invalid/">Another message</WebLink>
        <div ref={root}>
          <WebLink href="https://activity.invalid/">An activity link, not part of the reply</WebLink>
          <div data-assistant-selectable>{href ? <WebLink href={href}>Current link</WebLink> : null}</div>
        </div>
        <output>{links.map(link => link.href).join(",")}</output></>;
    }
    const { rerender } = render(<LiveMessage href={null} />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    rerender(<LiveMessage href="https://example.com/old" />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/^https:\/\/example.com\/old$/));
    rerender(<LiveMessage href="https://example.com/new" />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/^https:\/\/example.com\/new$/));
    rerender(<LiveMessage href={null} />);
    await waitFor(() => expect(screen.getByRole("status")).toBeEmptyDOMElement());
  });
});
