import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  __clearLogoFallbackCacheForTests,
  useLogoFallback,
} from "@/hooks/useLogoFallback";

function TestLogo({ urls }: { urls: string[] }) {
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(urls);
  if (!logoUrl) return <span>No logo</span>;
  return (
    <img
      src={logoUrl}
      alt="Logo"
      onLoad={onLogoLoad}
      onError={onLogoError}
    />
  );
}

describe("useLogoFallback", () => {
  afterEach(() => {
    __clearLogoFallbackCacheForTests();
  });

  it("remembers failed and loaded logo candidates across remounts", () => {
    const urls = [
      "https://bad.example/favicon.ico",
      "https://good.example/favicon.ico",
    ];
    const first = render(<TestLogo urls={urls} />);

    expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", urls[0]);

    fireEvent.error(screen.getByRole("img", { name: "Logo" }));
    expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", urls[1]);

    fireEvent.load(screen.getByRole("img", { name: "Logo" }));
    first.unmount();
    render(<TestLogo urls={urls} />);

    expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", urls[1]);
  });

  it("returns no logo once every candidate failed", () => {
    const urls = ["https://bad.example/favicon.ico"];
    render(<TestLogo urls={urls} />);

    fireEvent.error(screen.getByRole("img", { name: "Logo" }));

    expect(screen.getByText("No logo")).toBeInTheDocument();
  });
});
