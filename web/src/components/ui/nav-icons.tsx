// Menu icons drawn as separate parts so CSS can animate each one
// (see `.anim-icon` in styles/index.css). Same 24px grid and stroke as lucide.
const Svg = ({ name, children }: { name: string; children: React.ReactNode }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={2}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    className={`lucide anim-icon anim-${name}`}
  >
    {children}
  </svg>
);

export const KeyIcon = () => (
  <Svg name="key">
    <g className="key-body">
      <path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z" />
      <circle cx="16.5" cy="7.5" r=".5" fill="currentColor" />
    </g>
  </Svg>
);

export const ChartIcon = () => (
  <Svg name="chart">
    <path className="bar bar-1" d="M5 21v-4" />
    <path className="bar bar-2" d="M10 21v-8" />
    <path className="bar bar-3" d="M15 21v-6" />
    <path className="bar bar-4" d="M20 21v-11" />
    <path className="trend" pathLength={1} d="M3 11l5-5 5 4 8-7" />
  </Svg>
);

export const BookIcon = () => (
  <Svg name="book">
    <path
      className="page-left"
      d="M12 7a4 4 0 0 0-4-4H3a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h6a3 3 0 0 1 3 3z"
    />
    <path
      className="page-right"
      d="M12 7a4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3z"
    />
    <path d="M12 7v14" />
  </Svg>
);
