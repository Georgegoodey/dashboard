import { useQuery } from "@tanstack/react-query";
import { lettings } from "../lib";
import { ago } from "./format";

export function RunHistory() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: lettings.runs, refetchInterval: 8000 });
  if (!runs.data?.length) return <div className="muted">No runs yet.</div>;
  return (
    <div className="runs-wrap">
      <table className="table runs">
        <thead>
          <tr>
            <th>Job</th><th>When</th><th className="hide-narrow">Trigger</th><th>Status</th>
            <th className="num">Added</th><th className="num hide-narrow">Updated</th>
          </tr>
        </thead>
        <tbody>
          {runs.data.map((r) => (
            <tr key={r.id} title={r.error ?? ""}>
              <td>{r.job_id.replace(/_/g, " ")}</td><td>{ago(r.started_at)}</td><td className="hide-narrow">{r.trigger}</td><td>{r.status}</td>
              <td className="num">{r.rows_added}</td><td className="num hide-narrow">{r.rows_updated}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
