import { useQuery } from "@tanstack/react-query";
import { rpc } from "../lib/supabase";
import { ago, n } from "../lib/format";
import { Card, ErrorBox, PageHeader, Spinner } from "../components/ui";

export default function Offenders() {
  const q = useQuery({
    queryKey: ["offenders"],
    queryFn: () => rpc<any[]>("author_stats", { p_limit: 200 }),
  });
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Repeat offenders" sub="Commenters with hidden or negative comments across every post we hold — the shortlist for blocking." />
      <ErrorBox error={q.error} />
      {q.isLoading ? <Spinner /> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-faint">
              <tr>{["commenter", "comments", "posts", "negative", "judge hide", "decided hide", "last seen"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {((q.data as any[]) ?? []).map((a) => (
                <tr key={a.author}>
                  <td className="px-3 py-2"><a className="hover:text-accent" href={`https://www.instagram.com/${a.author}/`} target="_blank" rel="noreferrer">@{a.author}</a></td>
                  <td className="px-3 py-2 tabular-nums">{n(a.n_comments)}</td>
                  <td className="px-3 py-2 tabular-nums">{n(a.n_posts)}</td>
                  <td className="px-3 py-2 tabular-nums">{n(a.negative)}</td>
                  <td className="px-3 py-2 tabular-nums text-hide">{n(a.judged_hide)}</td>
                  <td className="px-3 py-2 tabular-nums font-semibold text-hide">{n(a.decided_hide)}</td>
                  <td className="px-3 py-2 text-xs text-faint">{ago(a.last_comment_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
