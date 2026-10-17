import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontSize: {
        // Patient half: everything at or above 24pt (= 32px) per docs/01 §2.
        patient: ["2rem", { lineHeight: "1.45" }],
        "patient-lg": ["2.75rem", { lineHeight: "1.3" }],
        "patient-xl": ["3.5rem", { lineHeight: "1.2" }],
      },
      colors: {
        ink: "#0d1117",
        slate: {
          950: "#080b11",
        },
        flag: "#b42318",
        confirm: "#15803d",
      },
    },
  },
  plugins: [],
};
export default config;
