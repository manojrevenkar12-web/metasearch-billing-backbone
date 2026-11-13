import type { CSSProperties, ReactNode } from "react";
import { color, font, leading, radius, size, space, weight } from "../app/theme";

export function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section aria-label={title} style={{ marginBottom: space[7] }}>
      <h2 style={{ fontFamily: font.board, fontWeight: weight.bold, fontSize: size.lg, lineHeight: leading.tight, margin: 0 }}>
        {title}
      </h2>
      {note && <p style={{ color: color.inkSoft, fontSize: size.sm, margin: `${space[1]} 0 ${space[4]}`, maxWidth: "68ch" }}>{note}</p>}
      {children}
    </section>
  );
}

export function Skeleton({ rows, dark = false }: { rows: number; dark?: boolean }) {
  const shade = dark ? color.boardRow : color.rule;
  return (
    <div role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} style={{ height: space[6], background: shade, borderRadius: radius.s, marginBottom: space[1], opacity: 0.7 }} />
      ))}
    </div>
  );
}

const box: CSSProperties = { border: `1px solid ${color.rule}`, borderRadius: radius.m, padding: space[5], fontSize: size.sm };

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" style={{ ...box, borderColor: color.wrong }}>
      <p style={{ margin: `0 0 ${space[3]}` }}>{message}</p>
      <button type="button" onClick={onRetry} style={buttonStyle}>Try again</button>
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div style={{ ...box, color: color.inkSoft }}>{children}</div>;
}

export const buttonStyle: CSSProperties = {
  fontFamily: font.body, fontWeight: weight.medium, fontSize: size.sm, padding: `${space[2]} ${space[4]}`,
  background: color.ink, color: color.paper, border: "none", borderRadius: radius.s, cursor: "pointer",
};
