import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

describe("UI shape system", () => {
  it("gives standard controls one shared radius", () => {
    render(
      <>
        <Button>Continue</Button>
        <Input aria-label="Name" />
        <Textarea aria-label="Description" />
      </>,
    );

    expect(screen.getByRole("button", { name: "Continue" })).toHaveClass("rounded-control");
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveClass("rounded-control");
    expect(screen.getByRole("textbox", { name: "Description" })).toHaveClass(
      "rounded-control",
    );
  });

  it("gives dialogs and alert dialogs one shared modal radius", () => {
    const dialog = render(
      <Dialog open>
        <DialogContent showCloseButton={false}>
          <DialogTitle>Edit name</DialogTitle>
          <DialogDescription>Choose a new name.</DialogDescription>
        </DialogContent>
      </Dialog>,
    );
    expect(screen.getByRole("dialog", { name: "Edit name" })).toHaveClass("rounded-modal");
    dialog.unmount();

    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogTitle>Delete item?</AlertDialogTitle>
          <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
        </AlertDialogContent>
      </AlertDialog>,
    );
    expect(screen.getByRole("alertdialog", { name: "Delete item?" })).toHaveClass(
      "rounded-modal",
    );
  });

  it("keeps floating surfaces and their items on the shared radius scale", () => {
    render(
      <DropdownMenu open>
        <DropdownMenuTrigger>Open menu</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>Rename</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );

    expect(screen.getByRole("menu")).toHaveClass("rounded-floating");
    expect(screen.getByRole("menuitem", { name: "Rename" })).toHaveClass(
      "rounded-control",
    );
  });
});
