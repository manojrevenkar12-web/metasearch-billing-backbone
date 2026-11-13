import { motion, useReducedMotion } from "framer-motion";
import type { InvoiceRow } from "../../shared/types";
import { EmptyState } from "../../shared/ui";
import { color, font, motion as m, radius, size, space, tracking, weight } from "../../app/theme";

const MONTHS = [
  { key: "2026-09", label: "September" },
  { key: "2026-10", label: "October" },
];

function day(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" }).toUpperCase();
}

function pct(v: number | null): string {
  if (v === null) return "not issued";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "±";
  return `${sign}${Math.abs(v).toFixed(2)}% avoidable`;
}

function Cell({ row, hideOnSmall }: { row?: InvoiceRow; hideOnSmall?: boolean }) {
  if (!row) return <div className={hideOnSmall ? "oct-hide" : undefined} />;
  const status = row.issued ? `ISSUED ${day(row.issued)}` : "HELD";
  const tone = row.issued ? color.flap : color.signal;
  return (
    <div className={hideOnSmall ? "oct-hide" : undefined} style={{ padding: `${space[2]} ${space[3]}` }}>
      <div style={{ fontFamily: font.board, fontWeight: weight.bold, letterSpacing: tracking.board, color: tone }}>
        {status}
        {row.notes > 0 && (
          <span style={{ marginLeft: space[2], color: color.signal }}>+{row.notes} NOTE{row.notes > 1 ? "S" : ""}</span>
        )}
      </div>
      <div style={{ fontSize: size.xs, color: color.flapDim }}>
        {pct(row.final_err_pct)}
        {row.held_days > 0 && ` · held ${row.held_days} day${row.held_days > 1 ? "s" : ""}`}
      </div>
    </div>
  );
}

export function CloseBoard({ invoices }: { invoices: InvoiceRow[] }) {
  const reduce = useReducedMotion();
  if (invoices.length === 0) {
    return <EmptyState>No invoices yet. The first close runs at 06:00 UTC on the 2nd of the month.</EmptyState>;
  }
  const partners = Array.from(new Map(invoices.map((r) => [r.partner, r])).values());
  const at = (p: string, month: string) => invoices.find((r) => r.partner === p && r.month === month);
  return (
    <div style={{ background: color.board, borderRadius: radius.m, padding: space[2], perspective: "900px" }}>
      <div className="board-row" style={{ color: color.flapDim, fontFamily: font.board, fontSize: size.sm, padding: `${space[2]} ${space[3]}` }}>
        <div>Partner</div>
        <div>Cur.</div>
        {MONTHS.map((mo, i) => (
          <div key={mo.key} className={i === 1 ? "oct-hide" : undefined} style={{ paddingLeft: space[3] }}>{mo.label}</div>
        ))}
      </div>
      {partners.map((p, i) => (
        <motion.div
          key={p.partner}
          className="board-row"
          initial={reduce ? false : { rotateX: -90, opacity: 0 }}
          animate={{ rotateX: 0, opacity: 1 }}
          transition={{ duration: m.flip, delay: i * m.stagger, ease: m.ease }}
          style={{ background: color.boardRow, color: color.flap, borderRadius: radius.s, marginTop: space[1], alignItems: "center", transformOrigin: "top" }}
        >
          <div style={{ padding: `${space[2]} ${space[3]}` }}>
            <div style={{ fontWeight: weight.medium }}>{p.name}</div>
            <div style={{ fontSize: size.xs, color: color.flapDim }}>{p.partner}</div>
          </div>
          <div style={{ fontFamily: font.board, color: color.flapDim }}>{p.currency}</div>
          {MONTHS.map((mo, j) => (
            <Cell key={mo.key} row={at(p.partner, mo.key)} hideOnSmall={j === 1} />
          ))}
        </motion.div>
      ))}
    </div>
  );
}
