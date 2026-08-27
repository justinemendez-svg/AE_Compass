/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/renderer/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'SF Pro Display', 'SF Pro Text', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
      colors: {
        surface: {
          primary: '#FFFFFF',
          secondary: '#F5F5F2',
          tertiary: '#EBEBEA',
        },
        accent: {
          matcha: '#D1F470',
          'matcha-dark': '#B8DC50',
          cactus: '#A1D78F',
          shamrock: '#2D4C33',
          fern: '#203524',
          pineapple: '#FEEB7E',
          licorice: '#11110D',
        },
        zd: {
          green: {
            50: '#F0FBD4',
            100: '#E6FAAB',
            200: '#E3F8A9',
            300: '#DAF68D',
            400: '#D1F470',
            500: '#B8DC50',
            600: '#A1D78F',
            700: '#2D4C33',
            800: '#203524',
            900: '#11110D',
          },
        },
      },
      boxShadow: {
        card: '0 1px 3px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04)',
        elevated: '0 4px 12px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.04)',
      },
    },
  },
  plugins: [],
};
