/** @type {import('tailwindcss').Config} */

const themeColor = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        background: themeColor("background"),
        surface: themeColor("surface"),
        "surface-muted": themeColor("surface-muted"),
        "surface-modal": themeColor("surface-modal"),
        "modal-muted": themeColor("modal-muted"),
        "surface-strong": themeColor("surface-strong"),
        border: themeColor("border"),

        foreground: themeColor("foreground"),
        "muted-foreground": themeColor("muted-foreground"),
        "disabled-foreground": themeColor("disabled-foreground"),

        primary: themeColor("primary"),
        "primary-hover": themeColor("primary-hover"),
        "primary-soft": themeColor("primary-soft"),
        "primary-border": themeColor("primary-border"),
        "primary-foreground": themeColor("primary-foreground"),

        secondary: themeColor("secondary"),
        "secondary-hover": themeColor("secondary-hover"),
        "secondary-soft": themeColor("secondary-soft"),
        "secondary-border": themeColor("secondary-border"),
        "secondary-foreground": themeColor("secondary-foreground"),

        accent: themeColor("accent"),
        "accent-hover": themeColor("accent-hover"),
        "accent-soft": themeColor("accent-soft"),
        "accent-border": themeColor("accent-border"),
        "accent-foreground": themeColor("accent-foreground"),

        danger: themeColor("danger"),
        "danger-hover": themeColor("danger-hover"),
        "danger-soft": themeColor("danger-soft"),
        "danger-border": themeColor("danger-border"),
        "danger-foreground": themeColor("danger-foreground"),

        "table-header": themeColor("table-header"),
        "table-row-hover": themeColor("table-row-hover"),
        "table-selected": themeColor("table-selected"),
        "table-border": themeColor("table-border"),

        "badge-bg": themeColor("badge-bg"),
        "badge-text": themeColor("badge-text"),
        "badge-border": themeColor("badge-border"),

        "input-bg": themeColor("input-bg"),
        "input-border": themeColor("input-border"),
        "input-border-focus": themeColor("input-border-focus"),
        "input-placeholder": themeColor("input-placeholder"),
        "input-disabled-bg": themeColor("input-disabled-bg"),

        "focus-ring": themeColor("focus-ring"),
      },
      borderColor: {
        DEFAULT: "rgb(var(--border) / 1)",
      },
      fontFamily: {
        sans: [
          "Figtree",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "DM Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "Liberation Mono",
          "Courier New",
          "monospace",
        ],
      },
      keyframes: {
        fadeInUp: {
          "0%": { opacity: "0", transform: "translateY(8px) scale(0.98)" },
          "100%": { opacity: "1", transform: "translateY(0) scale(1)" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        fadeInUp: "fadeInUp 180ms ease-out",
        fadeIn: "fadeIn 150ms ease-out",
      },
    },
  },
  plugins: [],
};
