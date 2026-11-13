// Every colour, size, space and duration the dashboard uses. Components read these; they hold no raw values.
export const color = {
  paper: "#F6F7F4",
  ink: "#1D232B",
  inkSoft: "#5A646F",
  rule: "#D6DBD6",
  signal: "#FFCD00", // wayfinding yellow: the one colour that means "look here"
  board: "#232A31",
  boardRow: "#2C343C",
  flap: "#F3F0E6",
  flapDim: "#9AA3AB",
  issued: "#1E7F55",
  held: "#A35F00",
  wrong: "#B83A2E",
  focus: "#2457C5",
} as const;

export const font = {
  body: "'Barlow', system-ui, sans-serif",
  board: "'Barlow Condensed', 'Barlow', system-ui, sans-serif",
} as const;

// A modular scale on a 16px base (ratio ~1.27)
export const size = { xs: "0.75rem", sm: "0.875rem", base: "1rem", md: "1.25rem", lg: "1.625rem", xl: "2.125rem" } as const;
export const weight = { regular: 400, medium: 500, bold: 700 } as const;
export const leading = { tight: 1.15, body: 1.5 } as const;
export const tracking = { board: "0.04em" } as const;

export const space = { 1: "4px", 2: "8px", 3: "12px", 4: "16px", 5: "24px", 6: "32px", 7: "48px", 8: "64px" } as const;
export const radius = { s: "3px", m: "6px" } as const;
export const measure = { prose: "68ch", page: "1180px", label: "11rem" } as const;
export const bar = { height: "10px" } as const;

export const motion = {
  flip: 0.42, // seconds for one board row to turn over
  stagger: 0.035,
  fade: 0.2,
  ease: [0.2, 0.7, 0.2, 1] as [number, number, number, number],
} as const;
