import type { Answer, Dashboard } from "./types";

export async function fetchDashboard(): Promise<Dashboard> {
  const res = await fetch("/data/dashboard.json");
  if (!res.ok) throw new Error(`The close data did not load (${res.status}).`);
  return res.json();
}

export async function ask(text: string): Promise<Answer> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error("The metrics service is not running. Start it with: mbb serve");
  return res.json();
}
