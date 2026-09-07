/** Tailwind CDN theme — Bitcoin OJ */
tailwind.config = {
  theme: {
    extend: {
      colors: {
        btc: {
          DEFAULT: '#f7931a',
          dark: '#e8850f',
          light: '#ffb84d',
          muted: '#f7931a33',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      boxShadow: {
        glow: '0 0 40px -8px rgba(247, 147, 26, 0.35)',
      },
    },
  },
};
