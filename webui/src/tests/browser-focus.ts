import { vi } from "vitest";

// happy-dom 16 gives native controls tabIndex -1 and treats FILTER_SKIP like
// FILTER_REJECT, hiding nested inputs/buttons from Radix's autofocus traversal.
// Scope these browser-compatible shims to tests that exercise real focus order.
export function mockBrowserFocus() {
  const tabIndex = vi.spyOn(HTMLElement.prototype, "tabIndex", "get")
    .mockImplementation(function (this: HTMLElement) {
      const explicit = this.getAttribute("tabindex");
      if (explicit !== null) return Number(explicit);
      if (this.matches("button, input, select, textarea, a[href]")) return 0;
      return -1;
    });
  const createTreeWalker = document.createTreeWalker.bind(document);
  const treeWalker = vi.spyOn(document, "createTreeWalker").mockImplementation((...args) => {
    const walker = createTreeWalker(...args);
    walker.nextNode = function (this: TreeWalker): Node | null {
      let node: Node | null = this.currentNode;
      let verdict: number = NodeFilter.FILTER_ACCEPT;
      while (node) {
        if (verdict !== NodeFilter.FILTER_REJECT && node.firstChild) {
          node = node.firstChild;
        } else {
          while (node && node !== this.root && !node.nextSibling) node = node.parentNode;
          if (!node || node === this.root) return null;
          node = node.nextSibling;
        }
        if (!node) return null;
        verdict = NodeFilter.FILTER_SKIP;
        if (this.whatToShow & (1 << (node.nodeType - 1))) {
          verdict = typeof this.filter === "function"
            ? this.filter(node)
            : this.filter?.acceptNode(node) ?? NodeFilter.FILTER_ACCEPT;
        }
        if (verdict === NodeFilter.FILTER_ACCEPT) {
          this.currentNode = node;
          return node;
        }
      }
      return null;
    };
    return walker;
  });
  return () => {
    treeWalker.mockRestore();
    tabIndex.mockRestore();
  };
}
