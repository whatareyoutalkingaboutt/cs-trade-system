import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui"],
        display: ["var(--font-display)", "ui-serif"],
      },
      colors: {
        brand: {
          50: "#f0f7ff",
          100: "#d9e9ff",
          200: "#b3d4ff",
          300: "#7fb6ff",
          400: "#4f96ff",
          500: "#2f6dff",
          600: "#1f4ed8",
          700: "#1b3db1",
          800: "#1b338d",
          900: "#1a2a6d",
        },
        ember: {
          50: "#fff6e5",
          100: "#ffe8c2",
          200: "#ffd08a",
          300: "#ffb650",
          400: "#ff9a1f",
          500: "#f97316",
          600: "#d45c0e",
          700: "#a7450b",
          800: "#7f330c",
          900: "#63290c",
        },
        slateblue: {
          50: "#f1f4ff",
          100: "#dfe6ff",
          200: "#c1ccff",
          300: "#9fa9ff",
          400: "#7b82ff",
          500: "#5a60ff",
          600: "#4546e6",
          700: "#3536b4",
          800: "#2b2c8a",
          900: "#23246a",
        }
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(79,150,255,0.2), 0 8px 30px rgba(31,78,216,0.25)",
        ember: "0 0 0 1px rgba(255,154,31,0.2), 0 10px 30px rgba(217,92,14,0.25)",
      },
      keyframes: {
        floaty: {
          "0%,100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-8px)" }
        },
        fadeUp: {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0px)" }
        },
        shimmer: {
          "0%": { backgroundPosition: "0% 50%" },
          "100%": { backgroundPosition: "100% 50%" }
        }
      },
      animation: {
        floaty: "floaty 6s ease-in-out infinite",
        fadeUp: "fadeUp 0.6s ease-out",
        shimmer: "shimmer 6s ease infinite",
      }
    }
  },
  plugins: [],
};

export default config;
