import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { BackgroundSettings } from "@/components/settings/overview/BackgroundSettings";

const background = vi.hoisted(() => ({
  hasBackground: true, image: null as Blob | null, blur: 5, veil: 88, busy: false, error: false,
  upload: vi.fn(), remove: vi.fn(), setStyle: vi.fn(), clearError: vi.fn(),
}));
vi.mock("@/providers/BackgroundProvider", () => ({ useBackground: () => background }));
vi.mock("@/hooks/useObjectUrl", () => ({ useObjectUrl: (image: Blob | null) => image ? "blob:preview" : null }));

beforeEach(() => {
  vi.clearAllMocks();
  background.image = new Blob(["image"], { type: "image/png" });
  background.remove.mockResolvedValue(true);
  background.upload.mockResolvedValue(true);
  background.setStyle.mockResolvedValue(true);
});

it("stages removal until saved, and cancel preserves the existing image", async () => {
  render(<BackgroundSettings />);
  fireEvent.click(screen.getByRole("button", { name: "Background" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  expect(background.remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Background" }));
  expect(screen.getByRole("button", { name: "Change image" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(background.remove).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("keeps the draft open when saving fails", async () => {
  background.remove.mockResolvedValue(false);
  render(<BackgroundSettings />);
  fireEvent.click(screen.getByRole("button", { name: "Background" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(background.remove).toHaveBeenCalledOnce());
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Save" })).toBeTruthy();
});

it("previews blur and saves only after confirmation", async () => {
  render(<BackgroundSettings />);
  fireEvent.click(screen.getByRole("button", { name: "Background" }));
  const slider = screen.getByRole("slider", { name: "Blur" });
  fireEvent.change(slider, { target: { value: "12" } });
  expect(screen.getByText("12 px")).toBeTruthy();
  expect(slider.style.getPropertyValue("--slider-progress")).toBe("60%");
  expect(slider.closest("[role=dialog]")?.querySelector(".background-settings-preview")?.getAttribute("style"))
    .toContain("--custom-background-blur: 12px");
  expect(background.setStyle).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Background" }));
  expect(screen.getByRole("slider", { name: "Blur" })).toHaveProperty("value", "5");
  fireEvent.change(screen.getByRole("slider", { name: "Blur" }), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(background.setStyle).toHaveBeenCalledWith(0, 88));
});

it("shows a useful error for oversized files before saving", () => {
  const { container } = render(<BackgroundSettings />);
  fireEvent.click(screen.getByRole("button", { name: "Background" }));
  const file = new File([new Uint8Array(6 * 1024 * 1024 + 1)], "large.png", { type: "image/png" });
  fireEvent.change(container.ownerDocument.querySelector('input[type="file"]')!, { target: { files: [file] } });
  expect(screen.getByRole("alert").textContent).toContain("6 MiB");
  expect(background.upload).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});

it("previews background fade and saves it with the blur", async () => {
  render(<BackgroundSettings />);
  fireEvent.click(screen.getByRole("button", { name: "Background" }));
  fireEvent.change(screen.getByRole("slider", { name: "Background fade" }), { target: { value: "40" } });
  expect(screen.getByText("40%")).toBeTruthy();
  expect(screen.getByRole("slider", { name: "Background fade" }).style.getPropertyValue("--slider-progress")).toBe("40%");
  expect(screen.getByRole("dialog").querySelector(".background-settings-preview")?.getAttribute("style"))
    .toContain("--custom-background-tint: 0.4");
  expect(background.setStyle).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(background.setStyle).toHaveBeenCalledWith(5, 40));
});

it("selects an image from the preview without saving before confirmation", () => {
  const { container } = render(<BackgroundSettings />);
  fireEvent.click(screen.getByRole("button", { name: "Background" }));
  const input = container.ownerDocument.querySelector<HTMLInputElement>('input[type="file"]')!;
  const openPicker = vi.spyOn(input, "click").mockImplementation(() => {});
  fireEvent.click(screen.getByRole("button", { name: "Change image" }));
  expect(openPicker).toHaveBeenCalledOnce();
  fireEvent.change(input, { target: { files: [new File(["image"], "new.png", { type: "image/png" })] } });
  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  expect(background.upload).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(background.upload).not.toHaveBeenCalled();
});
