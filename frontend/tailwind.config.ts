import type { Config } from "tailwindcss"

const token = (name: string) => `rgb(var(${name}) / <alpha-value>)`

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: token("--canvas"),
        surface: token("--surface"),
        ink: token("--ink"),
        muted: token("--muted"),
        line: token("--line"),
        accent: {
          DEFAULT: token("--accent"),
          soft: token("--accent-soft")
        },
        user: token("--user"),
        danger: {
          DEFAULT: token("--danger"),
          soft: token("--danger-soft")
        }
      },
      fontFamily: {
        sans: [
          "var(--font-sans)",
          "ui-sans-serif",
          "system-ui",
          "sans-serif"
        ]
      },
      boxShadow: {
        composer: "0 10px 40px rgba(22, 20, 17, 0.08)"
      }
    }
  },
  plugins: []
} satisfies Config
