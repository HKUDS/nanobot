import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  __clearLogoFallbackCacheForTests,
  useLogoFallback,
} from "@/hooks/useLogoFallback";

function TestLogo({ urls }: { urls: string[] }) {
  const { logoUrl, logoLoaded, onLogoError, onLogoLoad } = useLogoFallback(urls);
  if (!logoUrl) return <span>No logo</span>;
  return (
    <>
      <span>{logoLoaded ? "Loaded" : "Loading"}</span>
      <img src={logoUrl} alt="Logo" onLoad={onLogoLoad} onError={onLogoError} />
    </>
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
    expect(screen.getByText("Loading")).toBeInTheDocument();

    fireEvent.error(screen.getByRole("img", { name: "Logo" }));
    expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", urls[1]);

    fireEvent.load(screen.getByRole("img", { name: "Logo" }));
    expect(screen.getByText("Loaded")).toBeInTheDocument();
    first.unmount();
    render(<TestLogo urls={urls} />);

    expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", urls[1]);
    expect(screen.getByText("Loaded")).toBeInTheDocument();
  });

  it("returns no logo once every candidate failed", () => {
    const urls = ["https://bad.example/favicon.ico"];
    render(<TestLogo urls={urls} />);

    fireEvent.error(screen.getByRole("img", { name: "Logo" }));

    expect(screen.getByText("No logo")).toBeInTheDocument();
  });
});
