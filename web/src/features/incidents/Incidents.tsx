import type { IncidentRow } from "../../shared/types";
import { EmptyState } from "../../shared/ui";
import { color, font, size, space, weight } from "../../app/theme";

const WHAT: Record<string, string> = {
  outage: "Log shipping stopped",
  double_firing: "Every redirect logged twice",
  bot_storm: "Scraper clicking hotel offers",
  enum_drift: "New device value before the schema contract",
  fx_delay: "Reference rates stopped arriving",
};

export function Incidents({ incidents }: { incidents: IncidentRow[] }) {
  if (incidents.length === 0) return <EmptyState>No planted incidents in this world.</EmptyState>;
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: size.sm }}>
      <thead>
        <tr style={{ textAlign: "left", color: color.inkSoft }}>
          <th style={{ fontWeight: weight.medium, padding: space[2] }}>What happened</th>
          <th style={{ fontWeight: weight.medium, padding: space[2] }}>First check to fail</th>
          <th style={{ fontWeight: weight.medium, padding: space[2], textAlign: "right" }}>Hours to alert</th>
        </tr>
      </thead>
      <tbody>
        {incidents.map((r) => (
          <tr key={`${r.incident}-${r.start}`} style={{ borderTop: `1px solid ${color.rule}` }}>
            <td style={{ padding: space[2] }}>
              {WHAT[r.incident] ?? r.incident}
              <div style={{ color: color.inkSoft, fontSize: size.xs }}>{r.where}, {r.start.slice(0, 10)}</div>
            </td>
            <td style={{ padding: space[2], fontFamily: font.board }}>{r.caught ? r.first_check : "missed"}</td>
            <td style={{ padding: space[2], textAlign: "right", fontVariantNumeric: "tabular-nums", color: r.caught ? color.ink : color.wrong }}>
              {r.hours_to_alert ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
