import { useChatStore } from "./store";

/** Offline sample conversation: replays a scripted chat + tool calls, so the UI can be explored without a valid API key. */

const QUESTION = "Which boroughs are cheapest for a 2 bedroom home, and how many are there?";

const SQL = `SELECT borough, count(*) AS homes, round(avg(rent_pcm)) AS avg_rent_pcm
FROM v_properties
WHERE bedrooms = 2 AND borough IS NOT NULL
GROUP BY borough
ORDER BY avg_rent_pcm`;

const RESULT = JSON.stringify({ columns: ["borough", "homes", "avg_rent_pcm"], rows: [], note: "sample: the real result is shown above" });

const ANSWER = `The card above is the live result of that query: **average 2-bedroom rent by borough** with the number of homes behind each average.

Switch it between **Chart** and **Table**, or open **Customize** to change the chart type.

_This is a canned sample reply, generated offline. With a working model the assistant writes the SQL itself and summarises the real numbers._`;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function runDemo() {
  const s = useChatStore.getState();
  if (s.streaming) return;
  s.setError(undefined);
  s.setStreaming(true);
  s.setDemo(true);
  s.addMessage({ role: "user", content: QUESTION });
  await sleep(500);

  const id = crypto.randomUUID();
  const st = () => useChatStore.getState();
  st().startTool({ id, name: "query_sql", input: { sql: SQL }, startedAt: Date.now() });
  st().addResult(id, SQL);
  await sleep(700);
  st().endTool(id, RESULT);
  st().endResult(id, true);
  await sleep(300);

  for (const word of ANSWER.split(/(\s+)/)) {
    st().appendToken(word);
    await sleep(word.trim() ? 18 : 0);
  }
  st().setStreaming(false);
}
