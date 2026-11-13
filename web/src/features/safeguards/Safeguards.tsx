import type { VariantRow } from "../../shared/types";
import { EmptyState } from "../../shared/ui";
import { bar, color, measure, radius, size, space, weight } from "../../app/theme";

export function Safeguards({ variants }: { variants: VariantRow[] }) {
  if (variants.length === 0) return <EmptyState>Run scripts/evaluate.py to measure the safeguards.</EmptyState>;
  const max = Math.max(...variants.map((v) => v.final_error_pct), 0.01);
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {variants.map((v) => {
        const tone = v.key === "backbone" ? color.issued : v.key === "first_version" ? color.wrong : color.ink;
        return (
          <li key={v.key} style={{ marginBottom: space[3] }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: size.sm, gap: space[3] }}>
              <span style={{ fontWeight: v.key === "backbone" ? weight.bold : weight.regular, maxWidth: measure.prose }}>{v.label}</span>
              <span style={{ fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{v.final_error_pct.toFixed(2)}%</span>
            </div>
            <div style={{ background: color.rule, borderRadius: radius.s, height: bar.height, marginTop: space[1] }}>
              <div style={{ width: `${(100 * v.final_error_pct) / max}%`, background: tone, height: "100%", borderRadius: radius.s }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
