import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#07090f",
          900: "#0b0f17",
          850: "#10151f",
          800: "#151b27",
          700: "#1e2635",
          600: "#2b3547",
          500: "#3d4a60",
        },
        state: {
          shelf: "#3ddc84",
          lifting: "#ffd23d",
          hand: "#ff9f2d",
          returning: "#3dc4ff",
          basket: "#ff5cd6",
          lost: "#ff5f5f",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
