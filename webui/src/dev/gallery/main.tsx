import { createRoot } from "react-dom/client";

import { initializeI18n } from "@/i18n";
import { Gallery } from "./Gallery";
import "@/globals.css";
import "./gallery.css";

const root = document.getElementById("root");
if (!root) throw new Error("Gallery root element missing");

void initializeI18n().then(() => createRoot(root).render(<Gallery />));
