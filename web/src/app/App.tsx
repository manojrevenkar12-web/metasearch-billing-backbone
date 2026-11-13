import { useQuery } from "@tanstack/react-query";
import { fetchDashboard } from "../shared/api";
import { ErrorState, Section, Skeleton } from "../shared/ui";
import { CloseBoard } from "../features/board/CloseBoard";
import { Safeguards } from "../features/safeguards/Safeguards";
import { Incidents } from "../features/incidents/Incidents";
import { Ask } from "../features/ask/Ask";
import { color, font, leading, measure, size, space, weight } from "./theme";

const eur = new Intl.NumberFormat("en-GB", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

export function App() {
  const q = useQuery({ queryKey: ["dashboard"], queryFn: fetchDashboard });
  const d = q.data;
  return (
    <div style={{ fontFamily: font.body, lineHeight: leading.body }}>
      <header style={{ background: color.signal, padding: `${space[5]} ${space[5]}` }}>
        <div style={{ maxWidth: measure.page, margin: "0 auto" }}>
          <h1 style={{ fontFamily: font.board, fontWeight: weight.bold, fontSize: size.xl, lineHeight: leading.tight, margin: 0 }}>
            Partner billing close
          </h1>
          <p style={{ margin: `${space[1]} 0 0`, maxWidth: measure.prose }}>
            {d
              ? `September and October 2026 for 18 partners, ${eur.format(d.headline.true_billing_eur)} owed. When they first went out, invoices were ${d.headline.backbone_error_pct.toFixed(2)}% from the best these logs allow, against ${d.headline.first_version_error_pct.toFixed(2)}% for a first-version pipeline.`
              : "Redirect logs to partner invoices, with checks that hold a wrong invoice."}
          </p>
        </div>
      </header>
      <main style={{ maxWidth: measure.page, margin: "0 auto", padding: space[5] }}>
        {q.isPending && <Skeleton rows={10} dark />}
        {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => q.refetch()} />}
        {d && (
          <div className="grid" style={{ gap: space[6] }}>
            <div>
              <Section title="Close board" note="Each partner's invoice for the month, when it went out, and how far it is from the best these logs allow. A held invoice waited for a blocking check.">
                <CloseBoard invoices={d.invoices} />
              </Section>
              <Section title="Ask the billing data" note="Certified metrics only: a question no metric answers is refused, not guessed.">
                <Ask />
              </Section>
            </div>
            <div>
              <Section title="What each safeguard is worth" note="Avoidable billing error when invoices first went out, with one safeguard switched off at a time.">
                <Safeguards variants={d.variants} />
              </Section>
              <Section title="Planted incidents" note="Nothing told the pipeline about these.">
                <Incidents incidents={d.incidents} />
              </Section>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
