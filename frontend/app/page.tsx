"use client";

import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { diffLines } from "diff";
import { BookOpen, CheckCheck, ChevronRight, CirclePause, FlaskConical, History, Plus, Search } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Project = {id: number; name: string; status: string; domain: string; research_questions: string; scope: string};
type Artifact = {id: number; kind: string; revision: number; content: string; author: string; output_id?: number};
type Run = {
  id: string; project_id: number; status: string; node: string; revision: number; error: string;
  pending_review: {stage: string; content: string} | null; created_at: string; cost_usd?: number;
  artifacts?: Artifact[]; nodes?: {id: number; node: string; created_at: string}[];
  calls?: {id: number; node: string; status: string; input_tokens: number; output_tokens: number; cost_usd: number}[];
};
type Row = Record<string, unknown> & {id: number};

const labels: Record<string, string> = {
  queued: "等待执行", running: "执行中", waiting_review: "等待确认", completed: "已完成",
  cancelled: "已取消", failed: "执行失败", brief: "研究简报", brief_review: "确认简报",
  collect: "采集材料", search_plan: "搜索规划", coverage: "覆盖度评估", analyze: "提炼知识",
  outline: "文稿大纲", outline_review: "确认大纲", draft: "研究文稿", critique: "文稿审阅",
  final_review: "确认文稿", publish: "保存产出", published: "确认产出",
};

async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method, headers: {"Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : JSON.stringify(value.detail));
  return value;
}

function Markdown({text}: {text: string}) {
  return <div className="prose"><ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown></div>;
}

function Review({run}: {run: Run}) {
  const client = useQueryClient();
  const draftKey = `spectrum-review-${run.id}-${run.revision}`;
  const [draft] = useState(() => {
    const saved = window.localStorage.getItem(draftKey);
    return saved ? JSON.parse(saved) as {content: string; feedback: string} : null;
  });
  const [content, setContent] = useState(draft?.content ?? run.pending_review!.content);
  const [feedback, setFeedback] = useState(draft?.feedback ?? "");
  const [mode, setMode] = useState("编辑");
  useEffect(() => {
    window.localStorage.setItem(draftKey, JSON.stringify({content, feedback}));
  }, [draftKey, content, feedback]);
  const mutation = useMutation({
    mutationFn: (decision: string) => api(`runs/${run.id}/review`, "POST", {
      revision: run.revision, decision, content, feedback,
    }),
    onSuccess: () => {window.localStorage.removeItem(draftKey); client.invalidateQueries();},
  });
  return <section className="review">
    <div className="section-title"><h3>{labels[run.pending_review!.stage]} · 等待确认</h3>
      <span>版本 {run.revision}</span></div>
    <p className="muted">修改内容后继续研究。你的修改会保存为独立版本。</p>
    <p className="muted" role="status">审核草稿已保存在当前浏览器，可切换页面后继续编辑。</p>
    <div className="tabs">{["编辑", "预览", "修改差异"].map(item =>
      <button key={item} aria-pressed={mode === item} onClick={() => setMode(item)}>{item}</button>)}</div>
    {mode === "编辑" && <textarea className="editor" aria-label="审核内容" value={content} disabled={mutation.isPending}
      onChange={event => setContent(event.target.value)} />}
    {mode === "预览" && <Markdown text={content} />}
    {mode === "修改差异" && <pre className="diff">{diffLines(run.pending_review!.content, content).map((part, index) =>
      <span key={index} className={part.added ? "added" : part.removed ? "removed" : ""}>{part.value}</span>)}</pre>}
    <label>审核意见<textarea value={feedback} disabled={mutation.isPending} onChange={event => setFeedback(event.target.value)} rows={2}/></label>
    <div className="actions"><button className="primary" disabled={mutation.isPending || !content.trim()}
      onClick={() => mutation.mutate("approve")}>确认并继续</button>
      <button disabled={mutation.isPending} onClick={() => mutation.mutate("reject")}>结束本次研究</button></div>
    {mutation.error && <p role="alert" className="error">{mutation.error.message}</p>}
  </section>;
}

function RunDetail({id}: {id: string}) {
  const client = useQueryClient();
  const [streamError, setStreamError] = useState(false);
  const query = useQuery({queryKey: ["run", id], queryFn: () => api<Run>(`runs/${id}`)});
  const action = useMutation({mutationFn: (name: string) => api(`runs/${id}/${name}`, "POST"),
    onSuccess: () => client.invalidateQueries()});
  useEffect(() => {
    const source = new EventSource(`/api/runs/${id}/events`);
    source.onmessage = event => {
      const value = JSON.parse(event.data) as Run;
      client.setQueryData(["run", id], value);
      setStreamError(false);
      if (["completed", "failed", "cancelled"].includes(value.status)) source.close();
    };
    source.onerror = () => setStreamError(true);
    return () => source.close();
  }, [id, client]);
  if (query.error) return <p role="alert" className="error">{query.error.message}</p>;
  if (!query.data) return <p role="status">正在读取研究进度…</p>;
  const run = query.data;
  return <>
    <div className="run-header"><div><span className={`status ${run.status}`}>{labels[run.status]}</span>
      <h2>{labels[run.node] ?? run.node}</h2></div>
      <div className="run-meta"><span>模型费用 ${run.cost_usd?.toFixed(4) ?? "0.0000"}</span>
        <small>{new Date(run.created_at).toLocaleString("zh-CN")}</small></div></div>
    {streamError && <p role="status" className="error">实时连接中断，正在重新连接。</p>}
    {run.error && <p className="error" role="alert">{run.error}</p>}
    {action.error && <p className="error" role="alert">{action.error.message}</p>}
    <div className="actions">
      {["queued", "running", "waiting_review"].includes(run.status) &&
        <button disabled={action.isPending} onClick={() => action.mutate("cancel")}><CirclePause size={16}/>取消研究</button>}
      {run.status === "failed" && <button disabled={action.isPending} onClick={() => action.mutate("retry")}>从检查点恢复</button>}
    </div>
    <ol className="timeline">{["brief", "collect", "analyze", "outline", "draft", "publish"].map(node => {
      const done = run.nodes?.some(item => item.node === node);
      return <li key={node} className={done ? "done" : ""}><span className="step-dot" aria-hidden="true"/>{labels[node]}<span className="sr-only">{done ? "：已完成" : "：尚未完成"}</span></li>;
    })}</ol>
    {run.pending_review && run.status === "waiting_review" && <Review key={`${run.id}-${run.revision}`} run={run}/>}
    {run.status === "running" && <p role="status" className="muted">研究正在进行，完成当前阶段后会自动更新。</p>}
    {!!run.artifacts?.length && <section><h3>研究文档与历史版本</h3>{run.artifacts.slice().reverse().map(artifact =>
      <details key={artifact.id} open={artifact.kind === "published"}><summary>{labels[artifact.kind]} ·
        {artifact.author === "human" ? "人工确认" : "AI 生成"} · 版本 {artifact.revision}</summary>
        {artifact.output_id && <a className="download" href={`/api/outputs/${artifact.output_id}/markdown`}>下载 Markdown</a>}
        <Markdown text={artifact.content}/></details>)}</section>}
    <details><summary>模型调用记录 · {run.calls?.length ?? 0} 次</summary><div className="table-scroll"><table>
      <thead><tr><th>节点</th><th>状态</th><th>输入 Token</th><th>输出 Token</th><th>费用</th></tr></thead>
      <tbody>{run.calls?.map(call => <tr key={call.id}><td>{labels[call.node] ?? call.node}</td><td>{call.status}</td>
        <td>{call.input_tokens}</td><td>{call.output_tokens}</td><td>${call.cost_usd.toFixed(4)}</td></tr>)}</tbody>
    </table></div></details>
  </>;
}

function Library() {
  const [table, setTable] = useState("sources");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [domain, setDomain] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Row>();
  const data = useQuery({queryKey: ["library", table, offset], queryFn: () =>
    api<{items: Row[]; total: number}>(`${table}?limit=20&offset=${offset}`)});
  const results = useQuery({queryKey: ["search", search, domain], enabled: !!search, queryFn: () =>
    api<{results: {id: number; content: string; score: number}[]}>(`search?q=${encodeURIComponent(search)}&domain=${encodeURIComponent(domain)}`)});
  return <div className="library"><h2>知识浏览器</h2>
    <label>检索领域<input value={domain} onChange={event => setDomain(event.target.value)} placeholder="与课题的研究领域保持一致"/></label>
    <form className="search" onSubmit={event => {event.preventDefault(); setSearch(query);}}>
      <Search size={18}/><input aria-label="搜索知识" value={query} onChange={event => setQuery(event.target.value)}
        placeholder="搜索已有材料中的证据" required/><button disabled={results.isFetching}>搜索</button>
      {search && <button type="button" onClick={() => {setSearch(""); setQuery("");}}>清除搜索</button>}</form>
    {results.error && <p role="alert" className="error">{results.error.message}</p>}
    {search ? <section>{results.isFetching && <p>正在检索…</p>}{results.data?.results.map(result =>
      <details key={result.id}><summary>原文片段 #{result.id}</summary><Markdown text={result.content}/></details>)}
      {results.data?.results.length === 0 && <p className="empty">暂无匹配的原文片段。</p>}</section> : <>
      <div className="tabs">{[["sources", "材料"], ["wiki-cards", "知识卡"], ["outputs", "产出"], ["tags", "标签"]].map(([key, title]) =>
        <button key={key} aria-pressed={table === key} onClick={() => {setTable(key); setOffset(0); setSelected(undefined);}}>{title}</button>)}</div>
      {data.error && <p role="alert" className="error">{data.error.message}</p>}
      <div className="record-list">{data.data?.items.map(row => <button key={row.id} onClick={() => setSelected(row)}>
        <span>{String(row.title ?? row.concept ?? row.name)}</span><small>{String(row.domain ?? "")}</small><ChevronRight size={16}/></button>)}</div>
      {data.data?.total === 0 && <p className="empty">暂无记录。研究过程中产生的材料和知识会保存在这里。</p>}
      <div className="actions"><button disabled={offset === 0} onClick={() => setOffset(offset - 20)}>上一页</button>
        <span>共 {data.data?.total ?? 0} 条</span><button disabled={offset + 20 >= (data.data?.total ?? 0)} onClick={() => setOffset(offset + 20)}>下一页</button></div>
      {selected && <section><h3>{String(selected.title ?? selected.concept ?? selected.name)}</h3>
        {typeof selected.url === "string" && /^https:\/\//.test(selected.url) && <a href={selected.url} target="_blank" rel="noreferrer">查看原始材料</a>}
        <Markdown text={String(selected.content ?? selected.explanation ?? selected.extracted_summary ?? selected.description ?? "")}/></section>}
    </>}
  </div>;
}

function Workbench() {
  const client = useQueryClient();
  const [view, setView] = useState("研究");
  const [selected, setSelected] = useState<number>();
  const [runId, setRunId] = useState<string>();
  const [creating, setCreating] = useState(false);
  const [budget, setBudget] = useState(5);
  const projects = useQuery({queryKey: ["projects"], queryFn: () => api<Project[]>("projects")});
  const runs = useQuery({queryKey: ["runs", selected], queryFn: () =>
    api<Run[]>(selected ? `runs?project_id=${selected}` : "runs"), refetchInterval: 5000});
  const reviews = useQuery({queryKey: ["reviews"], queryFn: () => api<Run[]>("reviews"), refetchInterval: 5000});
  const logs = useQuery({queryKey: ["logs"], queryFn: () => api<{items: Row[]}>("logs"), enabled: view === "活动"});
  const project = projects.data?.find(item => item.id === selected);
  const create = useMutation({mutationFn: (body: unknown) => api<Project>("projects", "POST", body),
    onSuccess: value => {setSelected(value.id); setCreating(false); setRunId(undefined); client.invalidateQueries();}});
  const start = useMutation({mutationFn: () => api<{id: string}>(`projects/${selected}/runs`, "POST", {budget: {max_cost_usd: budget}}),
    onSuccess: value => {setRunId(value.id); client.invalidateQueries();}});
  const intake = useMutation({mutationFn: (body: unknown) => api("intake", "POST", body),
    onSuccess: () => client.invalidateQueries()});
  function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    create.mutate(Object.fromEntries(data));
  }
  return <div className="shell">
    <header><a className="brand" href="/"><FlaskConical size={25}/><strong>光谱 OS</strong><span>研究工作台</span></a>
      <span className="version">v0.5.0</span></header>
    <nav aria-label="主导航">{[["研究", FlaskConical], ["知识库", BookOpen], ["审核", CheckCheck], ["活动", History]].map(([name, Icon]) => {
      const title = name as string; const Symbol = Icon as typeof FlaskConical;
      return <button key={title} aria-current={view === title ? "page" : undefined} onClick={() => setView(title)}>
        <Symbol size={18}/>{title}{title === "审核" && !!reviews.data?.length && <span className="count">{reviews.data.length}</span>}</button>;
    })}</nav>
    <main>
      {view === "知识库" && <Library/>}
      {view === "活动" && <section><h2>活动记录</h2>{logs.error && <p className="error">{logs.error.message}</p>}
        {logs.data?.items.length === 0 && <p className="empty">暂无活动记录。</p>}
        {logs.data?.items.map(log => <div className="log" key={log.id}><span>{String(log.title)}</span><time>{String(log.created_at)}</time></div>)}</section>}
      {view === "审核" && <section><h2>等待确认的研究</h2>{reviews.data?.length === 0 && <p className="empty">当前没有待确认的研究。</p>}
        {reviews.isLoading && <p role="status">正在读取审核队列…</p>}
        {reviews.error && <p className="error" role="alert">{reviews.error.message}</p>}
        {reviews.data?.map(run => <button className="review-row" key={run.id} onClick={() => {setSelected(run.project_id); setRunId(run.id); setView("研究");}}>
          <span>{projects.data?.find(item => item.id === run.project_id)?.name}</span><span>{labels[run.pending_review?.stage ?? ""]}</span><ChevronRight size={18}/></button>)}</section>}
      {view === "研究" && <div className="workspace"><aside><div className="section-title"><h2>研究课题</h2>
        <button aria-label="创建课题" onClick={() => setCreating(true)}><Plus size={18}/></button></div>
        {projects.error && <p role="alert" className="error">{projects.error.message}</p>}
        {projects.isLoading && <p role="status">正在读取课题…</p>}
        {projects.data?.map(item => <button key={item.id} aria-pressed={selected === item.id} className={`project ${selected === item.id ? "selected" : ""}`}
          onClick={() => {setSelected(item.id); setRunId(undefined); setCreating(false);}}>
          <strong>{item.name}</strong><span>{item.domain || "未指定领域"} · {item.status}</span></button>)}
        {projects.data?.length === 0 && <p className="muted">从一个明确的研究问题开始。</p>}
      </aside><div className="workspace-main">
        {creating ? <form onSubmit={createProject} className="project-form"><h2>创建研究课题</h2>
          <label>课题名称<input name="name" required maxLength={500}/></label>
          <label>研究领域<input name="domain" maxLength={200}/></label>
          <label>研究问题<textarea name="research_questions" required rows={5}/></label>
          <label>范围与限制<textarea name="scope" rows={3}/></label>
          <div className="actions"><button className="primary" disabled={create.isPending}>保存课题</button>
            <button type="button" onClick={() => setCreating(false)}>取消创建</button></div>
          {create.error && <p className="error" role="alert">{create.error.message}</p>}
        </form> : project ? <>
          <div className="section-title"><h1>{project.name}</h1><span>{project.domain}</span></div>
          <p className="research-question">{project.research_questions}</p>
          <details><summary>研究设置与材料输入</summary><p>{project.scope || "尚未设置额外范围限制。"}</p>
            <label>模型费用上限（美元）<input type="number" min="0.01" max="100" step="0.1" value={budget}
              onChange={event => setBudget(Number(event.target.value))}/></label>
            <form onSubmit={event => {event.preventDefault(); const data = new FormData(event.currentTarget);
              intake.mutate({...Object.fromEntries(data), project_id: project.id});}}>
              <label>材料标题<input name="title" required/></label><label>材料 URL<input name="url" type="url" required placeholder="https://"/></label>
              <button disabled={intake.isPending}>{intake.isPending ? "正在提取材料…" : "添加材料"}</button>
              {intake.error && <p className="error" role="alert">{intake.error.message}</p>}
              {intake.isSuccess && <p role="status">材料已保存。</p>}</form></details>
          {runs.isLoading && <p role="status">正在读取运行记录…</p>}
          {runs.error && <p className="error" role="alert">{runs.error.message}</p>}
          <div className="actions"><button className="primary" disabled={start.isPending || runs.isLoading || !!runs.error || !!runs.data?.some(run => ["queued", "running", "waiting_review"].includes(run.status))}
            onClick={() => start.mutate()}>开始研究</button>
            <select aria-label="研究运行" value={runId ?? runs.data?.[0]?.id ?? ""} onChange={event => setRunId(event.target.value)}>
              <option value="" disabled>选择研究运行</option>{runs.data?.map(run => <option key={run.id} value={run.id}>
                {new Date(run.created_at).toLocaleString("zh-CN")} · {labels[run.status]}</option>)}</select></div>
          {start.error && <p className="error" role="alert">{start.error.message}</p>}
          {(runId ?? runs.data?.[0]?.id) ? <RunDetail key={runId ?? runs.data![0].id} id={runId ?? runs.data![0].id}/>
            : !runs.isLoading && !runs.error && <p className="empty">开始研究后，首先生成研究简报供你确认。</p>}
        </> : <div className="welcome"><FlaskConical size={40}/><h1>让每一个结论都有出处</h1>
          <p>围绕研究问题采集材料，提炼知识，在关键阶段确认方向。</p>
          <button className="primary" onClick={() => setCreating(true)}><Plus size={18}/>创建研究课题</button></div>}
      </div></div>}
    </main>
  </div>;
}

export default function Home() {
  const [client] = useState(() => new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}}));
  return <QueryClientProvider client={client}><Workbench/></QueryClientProvider>;
}
