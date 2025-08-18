import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{html,js,svelte,ts}"],

  theme: {
    extend: {
      colors: {
        primary: "#000000",
        secondary: "#111111",
        tertiary: "#222222",
        quaternary: "#333333",
        quinary: "#444444",
      }
    }
  },

  plugins: []
} as Config;
