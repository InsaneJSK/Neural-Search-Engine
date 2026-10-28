import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowUpRight, ArrowRight, Search, Plus, Github, Layers3, Compass, Clock3,
  SlidersHorizontal, ChevronRight, Check, Copy, X, BookOpen, Sparkles, Activity,
  LoaderCircle, CircleAlert, ExternalLink } from 'lucide-react';
import { answerParts, domain, safeUrl, seconds } from './utils.mjs';
import './styles.css';
import { DemoGate } from './DemoGate';

type Source = {source_id: string; title: string; url: string; snippet: string; rank: number;
  search_rank: number; dense_rank: number; bi_score: number; cross_score: number};
type Evidence = {query: string; search_id: string; backend: string; retrieved_at: string;
  candidate_count: number; reranked_count: number; results: Source[];
  timings_ms: {fetch_ms: number; bi_encoder_ms: number; cross_encoder_ms: number; total_ms: number}};
type Answer = {answer_status: 'available' | 'unavailable' | 'no_sources'; answer: string | null;
  provider: string | null; model: string | null; fallback_used: boolean; error?: string;
  answer_latency_ms: number; attempts: {provider: string; status: string; reason?: string}[]};
type Health = {status: string; busy: boolean; answer_busy: boolean};
const REPO = 'https://github.com/InsaneJSK/Neural-Search-Engine';
const EXAMPLES = [
  {label: 'Beyond keywords', query: 'What is semantic search, and how does it differ from keyword search?', icon: Search},
  {label: 'Understand retrieval', query: 'How does retrieval augmented generation reduce hallucinations?', icon: BookOpen},
  {label: 'Look under the hood', query: 'Why use a cross-encoder to rerank search results?', icon: Layers3},
];

async function post<T>(path: string, body: object): Promise<T> {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  let data;
  try { data = await response.json(); } catch { throw new Error('The service returned an unreadable response. Please retry.'); }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}). Please retry.`);
  return data as T;
}

function App() {
  const [query, setQuery] = useState('');
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [phase, setPhase] = useState<'idle' | 'search' | 'answer'>('idle');
  const [error, setError] = useState('');
  const [answerError, setAnswerError] = useState('');
  const [health, setHealth] = useState<Health | null>(null);
  const [autoAnswer, setAutoAnswer] = useState(true);
  const [top, setTop] = useState(5);
  const [history, setHistory] = useState<string[]>([]);
  const [about, setAbout] = useState(false);
  const [copied, setCopied] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const running = useRef(false);
  const busy = phase !== 'idle';

  useEffect(() => {
    let disposed = false;
    async function check() {
      try { const response = await fetch('/health', {signal: AbortSignal.timeout(4000)});
        if (!response.ok) throw new Error(); const data = await response.json(); if (!disposed) setHealth(data);
      } catch { if (!disposed) setHealth(null); }
    }
    void check(); const timer = setInterval(check, 15000);
    return () => { disposed = true; clearInterval(timer); };
  }, []);

  async function generate(result: Evidence) {
    setPhase('answer'); setAnswerError(''); setAnswer(null);
    try { setAnswer(await post<Answer>('/answer', {search_id: result.search_id})); }
    catch (err) { setAnswerError(err instanceof Error ? err.message : 'Could not generate an answer. Your sources are still available.'); }
  }

  async function search(value = query) {
    const clean = value.trim();
    if (!clean || running.current) return;
    running.current = true; setQuery(clean); setPhase('search'); setError(''); setAnswerError('');
    setEvidence(null); setAnswer(null); setCopied(false);
    try {
      const result = await post<Evidence>('/search', {query: clean, max_results: 20, rerank: 10, top});
      setEvidence(result);
      setHistory(old => [clean, ...old.filter(item => item !== clean)].slice(0, 6));
      if (autoAnswer && result.results.length) await generate(result);
    } catch (err) { setError(err instanceof Error ? err.message : 'Search unavailable. Please retry.'); }
    finally { setPhase('idle'); running.current = false; }
  }

  async function answerOnly() {
    if (!evidence || running.current) return;
    running.current = true;
    try { await generate(evidence); } finally { setPhase('idle'); running.current = false; }
  }

  function reset() {
    if (running.current) return;
    setQuery(''); setEvidence(null); setAnswer(null); setError(''); setAnswerError(''); input.current?.focus();
  }

  async function copyAnswer() {
    if (!answer?.answer || !evidence) return;
    try {
      await navigator.clipboard.writeText(answer.answer + '\n\nSources:\n' + evidence.results.map(s => `[${s.source_id}] ${s.title}\n${s.url}`).join('\n'));
      setCopied(true); setTimeout(() => setCopied(false), 2000);
    } catch { setAnswerError('Clipboard access is unavailable. You can select and copy the answer text.'); }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="NSE home"><span className="brand-mark">N<span>·</span></span><span>NSE<span className="brand-caption">NEURAL SEARCH ENGINE</span></span></a>
      <button className="new-search" onClick={reset} disabled={busy}><Plus size={16} /> New search <span className="new-icon">↗</span></button>
      <div className="nav-label">WORKSPACE</div>
      <button className="nav-item active" onClick={() => input.current?.focus()}><Compass size={17} /> Explore <span className="nav-dot" /></button>
      <button className="nav-item" onClick={() => setAbout(true)}><Layers3 size={17} /> Behind the search</button>
      <div className="history"><div className="nav-label">THIS SESSION</div>
        {history.length ? history.map(item => <button className="history-item" key={item} title={item} disabled={busy} onClick={() => void search(item)}><Clock3 size={14}/><span>{item}</span></button>) : <p className="history-empty">Your searches will appear here.<br/>A fresh trail of ideas.</p>}
      </div>
      <div className="sidebar-bottom"><div className="local-label"><span className="status-dot" /> Custom-trained retrieval</div><p>Two BERT models.<br/>One clearer path to the source.</p>
        <a href={REPO} target="_blank" rel="noreferrer"><Github size={15}/> Explore the project <ArrowUpRight size={14}/></a>
      </div>
    </aside>

    <div className="workspace">
      <header className="topbar"><div className="breadcrumb">Workspace <ChevronRight size={13}/><span>Explore</span></div>
        <div className={`connection ${health?.status === 'ready' ? 'online' : ''}`}><span className="status-dot" />{health?.status === 'ready' ? health.busy || health.answer_busy ? 'Service working' : 'Models ready' : 'Service unavailable'}</div>
      </header>
      <main className={evidence ? 'main results-main' : 'main'}>
        {!evidence && <section className="hero"><div className="eyebrow"><span className="tiny-orbit"/> SEARCH WITH UNDERSTANDING</div>
          <h1>Find meaning.<br/><span>Follow the evidence.</span></h1>
          <p>Go beyond matching words. Explore the web with neural<br className="desktop-break"/> ranking, clear sources, and answers you can trace.</p>
        </section>}
        {evidence && <div className="results-heading"><span className="eyebrow">YOUR RESEARCH</span><h1>From question to evidence.</h1></div>}
        <section className="search-area" aria-label="Search the web">
          <form className={`search-box ${busy ? 'is-busy' : ''}`} onSubmit={event => {event.preventDefault(); void search();}}>
            <div className="search-input-row"><Search size={23}/><label className="sr-only" htmlFor="query">Search question</label><textarea id="query" ref={input} rows={2} maxLength={2000} value={query} disabled={busy} placeholder="What would you like to understand?" onChange={event => setQuery(event.target.value)} onKeyDown={event => {if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); void search();}}}/></div>
            <div className="search-controls"><label className="answer-switch"><input type="checkbox" checked={autoAnswer} disabled={busy} onChange={event => setAutoAnswer(event.target.checked)}/><Sparkles size={14}/><span>Cited answer</span><span className="switch-track"/></label>
              <label className="source-limit"><SlidersHorizontal size={13}/><select aria-label="Number of sources" value={top} disabled={busy} onChange={event => setTop(Number(event.target.value))}><option value={3}>3 sources</option><option value={5}>5 sources</option><option value={10}>10 sources</option></select></label>
              <button className="search-submit" type="submit" aria-label={busy ? 'Search in progress' : 'Search'} disabled={!query.trim() || busy}>{busy ? <LoaderCircle size={17} className="spin"/> : <ArrowRight size={19}/>}<span>{busy ? 'Working' : 'Search'}</span></button>
            </div>
          </form>
          <div className="search-hint"><span><span className="status-dot"/> Live web · Neural reranking</span><span>Enter to search <span className="keycap">↵</span></span></div>
        </section>
        {error && <div className="notice error" role="alert"><CircleAlert size={18}/><div><strong>We couldn’t complete this search.</strong><p>{error}</p></div></div>}
        {phase === 'search' && <div className="loading-panel" role="status"><LoaderCircle className="spin" size={20}/><div><strong>Following the evidence…</strong><p>Finding web sources and ranking their relevance with both BERT models.</p></div></div>}

        {!evidence && phase !== 'search' && <>
          <section className="suggestions"><div className="section-kicker">A FEW PLACES TO START</div><div className="example-grid">{EXAMPLES.map(({label, query: suggestion, icon: Icon}) => <button key={label} onClick={() => void search(suggestion)} disabled={busy}><div className="example-top"><Icon size={17}/><ArrowUpRight size={15}/></div><span>{label}</span><p>{suggestion}</p></button>)}</div></section>
          <section className="method-preview"><div className="method-icon"><Layers3 size={21}/></div><div><h2>A second look at every result.</h2><p>Live web discovery. Custom-trained retrieval. A final relevance check.</p></div><button onClick={() => setAbout(true)} aria-label="Learn how neural ranking works"><ArrowUpRight size={19}/></button></section>
          <div className="pipeline-line"><span>01 <b>Discover</b></span><div/><span>02 <b>Retrieve</b></span><div/><span>03 <b>Rerank</b></span><div/><span>04 <b>Understand</b></span></div>
        </>}

        {evidence && <div className="results-grid"><div className="results-column">
          <section className="answer-card" aria-label="Cited answer"><div className="card-heading"><span className="answer-title"><Sparkles size={17}/> The short answer</span>{answer?.answer && <button className="icon-button" onClick={() => void copyAnswer()} aria-label={copied ? 'Answer copied' : 'Copy answer and sources'}>{copied ? <Check size={16}/> : <Copy size={16}/>}</button>}</div>
            {phase === 'answer' ? <div className="answer-loading" role="status"><LoaderCircle className="spin" size={18}/><div>Reading your ranked sources…<small>Groq first, with local Ollama as backup.</small></div></div> : answer?.answer ? <>
              <div className="answer-text">{answerParts(answer.answer, evidence.results.map(s => s.source_id)).map((part: {text: string; ids: string[]}, index: number) => part.ids.length ? <React.Fragment key={index}>{part.ids.map(id => <a className="citation" key={id} href={`#source-${id}`} aria-label={`Jump to source ${id}`}>{id}</a>)}</React.Fragment> : <React.Fragment key={index}>{part.text}</React.Fragment>)}</div>
              <div className="answer-meta"><span>{answer.provider === 'groq' ? 'Groq' : 'Ollama'} · {answer.model}</span><span>{seconds(answer.answer_latency_ms)}{answer.fallback_used ? ' · Local fallback' : ''}</span></div>
              <p className="verification-note">Citations link to retrieved excerpts. Claims are not independently fact-checked.</p>
            </> : <div className="answer-placeholder"><p>{answer?.error || (evidence.results.length ? 'Get a concise answer grounded in these sources.' : 'No sources to build an answer from. Try a broader query.')}</p>{evidence.results.length > 0 && <button className="text-button" disabled={busy} onClick={() => void answerOnly()}><Sparkles size={14}/>{answer ? 'Retry answer' : 'Generate cited answer'}<ArrowRight size={14}/></button>}</div>}
            {answerError && <p className="inline-error" role="alert">{answerError}</p>}
          </section>
          <div className="sources-heading"><h2>Ranked sources <span>{evidence.results.length}</span></h2><span>Ordered by relevance</span></div>
          {!evidence.results.length && <div className="notice"><Search size={18}/><p>No results found. Try fewer constraints or a different question.</p></div>}
          {evidence.results.map(source => <article className="source-card" id={`source-${source.source_id}`} key={source.source_id} tabIndex={-1}>
            <div className="source-top"><span className="source-number">{String(source.rank).padStart(2, '0')}</span><span className="source-domain">{domain(source.url)}</span><span className="source-id">{source.source_id}</span></div>
            <h3>{safeUrl(source.url) ? <a href={safeUrl(source.url)!} target="_blank" rel="noreferrer">{source.title}<ArrowUpRight size={17}/></a> : source.title}</h3>
            <Excerpt text={source.snippet}/>
            <details className="ranking-details"><summary><Activity size={13}/> Ranking details <ChevronRight size={13}/></summary><div className="rank-stages"><div><small>Web position</small><strong>#{source.search_rank}</strong></div><ArrowRight size={14}/><div><small>Dense shortlist</small><strong>#{source.dense_rank}</strong></div><ArrowRight size={14}/><div><small>Final position</small><strong>#{source.rank}</strong></div></div><div className="scores"><span>Bi-encoder <b>{source.bi_score.toFixed(4)}</b></span><span>Cross-encoder <b>{source.cross_score.toFixed(4)}</b></span></div><p>Model relevance scores, not confidence percentages.</p></details>
          </article>)}
        </div><aside className="trace-card"><div className="card-heading"><span><Layers3 size={16}/> Search trace</span><span className="complete-dot"><Check size={12}/></span></div><p className="trace-intro">A clear path from the web<br/>to your reading list.</p>
          <div className="trace-step"><span>1</span><div><strong>Discover</strong><p>{evidence.candidate_count} web excerpts</p><small>{seconds(evidence.timings_ms.fetch_ms)} · {evidence.backend}</small></div></div>
          <div className="trace-step"><span>2</span><div><strong>Retrieve</strong><p>{evidence.reranked_count} shortlisted</p><small>{seconds(evidence.timings_ms.bi_encoder_ms)} · BERT bi-encoder</small></div></div>
          <div className="trace-step"><span>3</span><div><strong>Rerank</strong><p>{evidence.results.length} sources selected</p><small>{seconds(evidence.timings_ms.cross_encoder_ms)} · BERT cross-encoder</small></div></div>
          <div className="trace-total"><span>Retrieval time</span><strong>{seconds(evidence.timings_ms.total_ms)}</strong></div><p className="trace-footnote">Ranking compares web excerpts, not full pages.</p><button className="text-button" onClick={() => setAbout(true)}>About the models <ArrowUpRight size={13}/></button>
        </aside></div>}
      </main>
      <footer><span>NSE <span className="footer-dot">/</span> Built to make search explainable.</span><a href={`${REPO}#evaluation`} target="_blank" rel="noreferrer">Training & evaluation <ArrowUpRight size={12}/></a></footer>
    </div>
    {about && <About close={() => setAbout(false)}/>}
  </div>;
}

function About({close}: {close: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="about-dialog" aria-labelledby="about-title" onCancel={close} onClick={event => {if (event.target === dialog.current) close();}}>
    <div className="dialog-top"><span className="eyebrow">BEHIND THE SEARCH</span><button className="icon-button" onClick={close} aria-label="Close model information"><X size={19}/></button></div>
    <h2 id="about-title">Trained to take<br/>a closer look.</h2><p className="dialog-intro">NSE brings custom neural ranking to live web search. Each source takes the same three-step journey before it reaches you.</p>
    <div className="model-row"><span>01</span><div><h3>Live discovery</h3><p>Tavily finds up to 20 web excerpts for your question.</p></div></div>
    <div className="model-row"><span>02</span><div><h3>BERT bi-encoder</h3><p>Trained on 200,000 MS MARCO triples to compare query and passage meaning, then select a shortlist.</p></div></div>
    <div className="model-row"><span>03</span><div><h3>BERT cross-encoder</h3><p>Trained on 1.78 million expanded triples to read each query–passage pair together and rerank the shortlist.</p></div></div>
    <div className="effort-note"><strong>100+ hours</strong><span>Across setup, training, and experimentation.<br/>Author-reported effort, not measured GPU hours.</span></div>
    <p className="dialog-limit">The trained pipeline did not outperform Tavily in the recorded 30-query live-web evaluation. See the results, latency trade-offs, and limitations in the repository.</p>
    <a className="repository-link" href={REPO} target="_blank" rel="noreferrer"><Github size={16}/> Explore the implementation <ExternalLink size={14}/></a>
  </dialog>;
}

function Excerpt({text}: {text: string}) {
  const [expanded, setExpanded] = useState(false);
  const long = text.length > 320;
  return <><p className={`source-snippet ${long && !expanded ? 'clamped' : ''}`}>{text}</p>{long && <button className="excerpt-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? 'Show less' : 'Read full excerpt'}</button>}</>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode>{import.meta.env.VITE_DEMO_GATE === '1' ? <DemoGate><App/></DemoGate> : <App/>}</React.StrictMode>);
