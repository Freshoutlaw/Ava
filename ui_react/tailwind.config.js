/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0a0a0f',
        surface: '#111118',
        surface2: '#18181f',
        border: '#2a2a35',
        accent: '#00e5a0',
        accent2: '#d4af5a',
        muted: '#666680',
      },
    },
  },
  plugins: [],
};
