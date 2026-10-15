import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Brand palette: lavender white, midnight navy, muted teal, mint, pale lavender
        lavender: {
          50: "#FFFFFF",
          100: "#F5F5FC",
          200: "#E4E4F8",
          300: "#D3D4F0",
          400: "#BFC1E2",
        },
        navy: {
          400: "#7A8099",
          500: "#5D6380",
          600: "#474C68",
          700: "#3A3F58",
          800: "#303650",
          900: "#262A40",
          950: "#1C2032",
        },
        teal: {
          100: "#E3F2F1",
          200: "#C9E6E4",
          300: "#8FC4C2",
          400: "#5FA5A3",
          500: "#438D8B",
          600: "#37726F",
          700: "#2C5A58",
        },
        mint: {
          100: "#EAFBF4",
          200: "#C9F7E5",
          300: "#A5EBD1",
          400: "#7EDCBB",
        },

        /*
         * Legacy surfaces remapped onto the light theme. The original scale ran
         * dark-on-light (ink-950 = page, ink-700 = border); the new scale keeps
         * the same class names so every panel/border inherits the soft palette.
         */
        ink: {
          950: "#FFFFFF",
          900: "#FBFBFE",
          850: "#F5F5FC",
          800: "#F5F5FC",
          700: "#E4E4F8",
          600: "#D6D7EF",
          500: "#C2C4E0",
        },
        /*
         * Text greys, re-weighted for light surfaces: slate-200 is now the
         * primary navy body colour instead of a near-white highlight.
         */
        slate: {
          50: "#FFFFFF",
          100: "#F5F5FC",
          200: "#303650",
          300: "#3A3F58",
          400: "#5D6380",
          500: "#7A8099",
          600: "#9DA2BD",
          700: "#C2C4DE",
          800: "#E4E4F8",
          900: "#F5F5FC",
          950: "#FFFFFF",
        },
        // Success / positive accents reuse the muted teal family
        emerald: {
          200: "#D3F0EE",
          300: "#2C5A58",
          400: "#438D8B",
          500: "#438D8B",
          600: "#37726F",
          700: "#2C5A58",
        },
        // Attention accents, softened so they stay calm on white
        amber: {
          200: "#F6EBD4",
          300: "#A8762A",
          400: "#C99A46",
          500: "#C99A46",
          600: "#B3843A",
        },
        // Fault accents, softened
        rose: {
          200: "#F7E2E0",
          300: "#B4564F",
          400: "#C9645F",
          500: "#C9645F",
          600: "#B4564F",
        },
        // Product state hues: recognisable, but muted to fit the palette
        state: {
          shelf: "#438D8B",
          lifting: "#C99A46",
          hand: "#C97A54",
          returning: "#5F84C4",
          basket: "#7C74C9",
          lost: "#C9645F",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        card: "1.25rem",
        shell: "2rem",
      },
      boxShadow: {
        soft: "0 1px 2px rgba(48, 54, 80, 0.04), 0 8px 24px -8px rgba(48, 54, 80, 0.10)",
        lift: "0 2px 4px rgba(48, 54, 80, 0.05), 0 18px 40px -12px rgba(48, 54, 80, 0.16)",
        float:
          "0 4px 10px rgba(48, 54, 80, 0.06), 0 32px 70px -20px rgba(48, 54, 80, 0.24)",
      },
    },
  },
  plugins: [],
};

export default config;
