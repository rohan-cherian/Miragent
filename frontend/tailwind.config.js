/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          50: '#f0f4f8',
          100: '#d9e4f0',
          500: '#3b6fa0',
          700: '#2a5080',
          900: '#1B2A4A'
        },
        brand: '#1B2A4A'
      }
    }
  },
  plugins: []
}
