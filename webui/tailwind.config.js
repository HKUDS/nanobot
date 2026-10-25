import animate from "tailwindcss-animate";
import typography from "@tailwindcss/typography";
import plugin from "tailwindcss/plugin";

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
    ...(process.env.NODE_ENV === "production" ? ["!./src/dev/**"] : []),
    "../nanobot/channels/*/webui/**/*.{ts,tsx}",
    "./node_modules/streamdown/dist/*.js",
  ],
  theme: {
    container: {
      center: true,
      padding: "1rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      // Text roles own their metrics; reading preferences never change the rem grid.
      fontSize: {
        ui: ["0.8125rem", { lineHeight: "1.25rem", fontWeight: "400" }],
        "ui-label": ["0.75rem", { lineHeight: "1.125rem", fontWeight: "500" }],
        "ui-heading": ["0.8125rem", { lineHeight: "1.25rem", fontWeight: "600" }],
        "ui-body": ["0.875rem", { lineHeight: "1.25rem", fontWeight: "400" }],
        "control-label": ["0.875rem", { lineHeight: "1.25rem", fontWeight: "500" }],
        caption: ["0.75rem", { lineHeight: "1.125rem", fontWeight: "400" }],
        title: ["1.25rem", { lineHeight: "1.75rem", fontWeight: "600" }],
        reading: ["var(--text-reading-size)", { lineHeight: "var(--cjk-line-height)", fontWeight: "400" }],
        "reading-small": ["calc(var(--text-reading-size) * 0.875)", { lineHeight: "var(--cjk-line-height)", fontWeight: "400" }],
        code: ["var(--text-code-size)", { lineHeight: "1.6", fontWeight: "400" }],
        "code-dense": ["var(--text-code-dense-size)", { lineHeight: "1.6", fontWeight: "400" }],
        composer: ["max(16px, var(--text-reading-size))", { lineHeight: "1.5", fontWeight: "400" }],
      },
      fontFamily: {
        sans: [
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "Roboto",
          '"Helvetica Neue"',
          "Arial",
          '"Noto Sans"',
          '"Noto Sans SC"',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          '"Microsoft YaHei"',
          "sans-serif",
          '"Apple Color Emoji"',
          '"Segoe UI Emoji"',
        ],
        mono: [
          '"JetBrains Mono"',
          '"SFMono-Regular"',
          '"SF Mono"',
          '"Fira Code"',
          '"Cascadia Code"',
          '"Source Code Pro"',
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        mark: "var(--radius-mark)",
        compact: "var(--radius-compact)",
        control: "var(--radius-control)",
        floating: "var(--radius-floating)",
        panel: "var(--radius-panel)",
        modal: "var(--radius-modal)",
        prominent: "var(--radius-prominent)",
      },
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        "diff-added": {
          DEFAULT: "var(--diff-added)",
          foreground: "var(--diff-added-foreground)",
        },
        "diff-deleted": {
          DEFAULT: "var(--diff-deleted)",
          foreground: "var(--diff-deleted-foreground)",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        sidebar: {
          DEFAULT: "hsl(var(--sidebar))",
          foreground: "hsl(var(--sidebar-foreground))",
          content: "hsl(var(--sidebar-content))",
          "muted-foreground": "hsl(var(--sidebar-muted-foreground))",
          selected: "hsl(var(--sidebar-selected))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
        },
        settings: {
          canvas: "hsl(var(--settings-canvas))",
          surface: "hsl(var(--settings-surface))",
        },
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [
    animate,
    typography,
    plugin(({ addVariant, addUtilities }) => {
      addUtilities({ ".rounded-full": { cornerShape: "round" } });
      // Revealing controls on emulated hover can consume the first Safari
      // tap. Keep these sidebar hover effects on hover-capable pointers.
      addVariant("media-hover", "@media (hover: hover)");
    }),
  ],
};
