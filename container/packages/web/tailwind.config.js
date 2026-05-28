/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        circuit: {
          50: '#f0f5ff',
          100: '#e0eaff',
          500: '#4f6df5',
          600: '#3b5bdb',
          700: '#2b4acb',
          800: '#1e3a8a',
          900: '#1a2f6b',
        },
      },
    },
  },
  plugins: [],
}
