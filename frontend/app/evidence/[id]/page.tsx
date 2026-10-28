"use client";

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { use, useState } from "react";
import ReactMarkdown from "react-markdown";

type Evidence = {claim: {statement: string}; evidence: {chunk_id: number; quote: string; content: string;
  version: string; relation: string; source: {title: string; url: string}}[]};

function Content({id}: {id: string}) {
  const query = useQuery({queryKey: ["evidence", id], queryFn: async () => {
    const response = await fetch(`/api/evidence/${id}`);
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail);
    return value as Evidence;
  }});
  const data = query.data;
  return <main className="evidence-page"><a href="/">返回研究工作台</a><h1>原文证据</h1>
    {query.error && <div role="alert"><p className="error">{query.error.message}</p>
      <button onClick={() => query.refetch()} disabled={query.isFetching}>重新读取证据</button></div>}
    {data && <><h2>{data.claim.statement}</h2>{data.evidence.map(item => <section key={item.chunk_id}>
      <h3>{item.source.title}</h3><a href={item.source.url} rel="noreferrer" target="_blank">查看来源</a>
      <blockquote>{item.quote}</blockquote><small>{item.relation === "supports" ? "支持证据" : "反驳证据"} · 材料版本 {item.version.slice(0, 12)}</small>
      <details><summary>查看完整片段</summary><div className="prose"><ReactMarkdown>{item.content}</ReactMarkdown></div></details>
    </section>)}</>}
    {query.isLoading && <p role="status">正在读取证据…</p>}
  </main>;
}

export default function EvidencePage({params}: {params: Promise<{id: string}>}) {
  const {id} = use(params);
  const [client] = useState(() => new QueryClient({defaultOptions: {queries: {retry: false}}}));
  return <QueryClientProvider client={client}><Content id={id}/></QueryClientProvider>;
}
