import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{html,js,svelte,ts}"],
  darkMode: 'class',

  theme: {
    extend: {
      fontFamily: {
        // Matches :root --font-sans in app.css — change both when switching fonts
        sans: ["var(--font-sans)"],
      },
    }
  },

  plugins: []
} as Config;
