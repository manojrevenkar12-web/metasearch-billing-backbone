import { useMutation } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useState, type FormEvent } from "react";
import { ask } from "../../shared/api";
import { ErrorState, EmptyState, buttonStyle } from "../../shared/ui";
import { color, font, motion as m, radius, size, space } from "../../app/theme";

const EXAMPLES = ["billed clicks by brand last month", "invalid traffic share on hotelscombined in Germany in October, by reason", "invoices by kind"];

export function Ask() {
  const [text, setText] = useState(EXAMPLES[0]);
  const q = useMutation({ mutationFn: ask });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) q.mutate(text.trim());
  };
  return (
    <div>
      <form onSubmit={submit} style={{ display: "flex", gap: space[2], flexWrap: "wrap" }}>
        <label htmlFor="q" style={{ position: "absolute", left: "-9999px" }}>Question</label>
        <input id="q" value={text} onChange={(e) => setText(e.target.value)}
          style={{ flex: 1, minWidth: "16rem", fontFamily: font.body, fontSize: size.base, padding: space[2], border: `1px solid ${color.rule}`, borderRadius: radius.s }} />
        <button type="submit" style={buttonStyle} disabled={q.isPending}>{q.isPending ? "Asking" : "Ask"}</button>
      </form>
      <div style={{ display: "flex", gap: space[2], flexWrap: "wrap", margin: `${space[2]} 0 ${space[4]}` }}>
        {EXAMPLES.map((x) => (
          <button key={x} type="button" onClick={() => setText(x)}
            style={{ ...buttonStyle, background: "transparent", color: color.inkSoft, border: `1px solid ${color.rule}` }}>{x}</button>
        ))}
      </div>
      <AnimatePresence mode="wait">
        {q.isError && (
          <motion.div key="err" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: m.fade }}>
            <ErrorState message={(q.error as Error).message} onRetry={() => q.mutate(text)} />
          </motion.div>
        )}
        {q.data && !q.data.answered && (
          <motion.div key="refused" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: m.fade }}>
            <EmptyState>Not answered: {q.data.refusal}</EmptyState>
          </motion.div>
        )}
        {q.data?.answered && (
          <motion.div key="ok" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: m.fade }}>
            {q.data.rows && q.data.rows.length === 0 ? (
              <EmptyState>{q.data.metric}: no rows for that question.</EmptyState>
            ) : (
              <table style={{ fontSize: size.sm, borderCollapse: "collapse" }}>
                <caption style={{ textAlign: "left", marginBottom: space[2] }}>{q.data.metric} ({q.data.unit})</caption>
                <tbody>
                  {q.data.rows?.map((r, i) => (
                    <tr key={i} style={{ borderTop: `1px solid ${color.rule}` }}>
                      {r.map((c, j) => <td key={j} style={{ padding: `${space[1]} ${space[3]}`, fontVariantNumeric: "tabular-nums" }}>{String(c)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <details style={{ marginTop: space[3], fontSize: size.xs, color: color.inkSoft }}>
              <summary>SQL the catalog wrote</summary>
              <code>{q.data.sql}</code>
            </details>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
