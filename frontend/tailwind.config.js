/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        gray: {
          // Offset surface between gray-700 and gray-800 — used for raised dark
          // header rows (table column headers, group headers) so they read as a
          // slightly lighter band against the gray-800 card / gray-900 page.
          750: '#2b3544',
        },
      },
    },
  },
  plugins: [],
}
