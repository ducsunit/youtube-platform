import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, CheckCircle2, AlertCircle, PlayCircle, RefreshCw, ChevronRight, Zap, Compass } from '../components/Icons';
import { approveResearch, getResearchLog, startResearch, startRun, runAtlas, suggestKeywords } from '../api';
import { useChannelContext } from '../contexts/ChannelContext';
import type { ResearchLogEvent, ResearchOpportunity, ResearchRun, AtlasSubNiche, AtlasResponse, SuggestKeyword } from '../types';

const COUNTRIES = [{ code: 'JP', label: 'Japan' }, { code: 'US', label: 'United States' }, { code: 'VN', label: 'Vietnam' }];
const LANGUAGES = [{ code: 'ja', label: '日本語' }, { code: 'en', label: 'English' }, { code: 'vi', label: 'Tiếng Việt' }];

type Mode = 'standard' | 'atlas';

export function ResearchPage() {
  const navigate = useNavigate();
  const { currentChannel, loading: channelLoading } = useChannelContext();
  const [mode, setMode] = useState<Mode>('standard');
  const [country, setCountry] = useState('VN');
  const [language, setLanguage] = useState('vi');
  const [keyword, setKeyword] = useState('');
  const [research, setResearch] = useState<ResearchRun | null>(null);
  const [atlasResult, setAtlasResult] = useState<AtlasResponse | null>(null);
  const [selected, setSelected] = useState<ResearchOpportunity | null>(null);
  const [atlasSelected, setAtlasSelected] = useState<AtlasSubNiche[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [logEvents, setLogEvents] = useState<ResearchLogEvent[]>([]);
  const [showLog, setShowLog] = useState(false);
  const [logLoading, setLogLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<SuggestKeyword[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestLoading, setSuggestLoading] = useState(false);

  async function loadLog() {
    if (!research) return;
    setLogLoading(true);
    try {
      const result = await getResearchLog(research.research_run_id, scope);
      setLogEvents(result.events);
      setShowLog(true);
    } catch (err) { setError(String(err)); } finally { setLogLoading(false); }
  }

  if (channelLoading || !currentChannel) return <div className="page"><div className="empty-state">Chọn hoặc đăng ký channel trước khi research.</div></div>;
  const channel = currentChannel;
  const scope = { user_id: channel.user_id, channel_id: channel.channel_id };

  async function runResearch() {
    setBusy(true); setError(''); setMessage(''); setResearch(null); setSelected(null); setLogEvents([]); setShowLog(false);
    try {
      const result = await startResearch({ ...scope, keyword, country, language });
      setResearch(result); setMessage('Research hoàn tất. Hãy kiểm tra evidence và risk flags trước khi approve.');
    } catch (err) { setError(String(err)); } finally { setBusy(false); }
  }

  async function runAtlasResearch() {
    setBusy(true); setError(''); setMessage(''); setAtlasResult(null); setAtlasSelected([]); setLogEvents([]); setShowLog(false);
    try {
      const result = await runAtlas({ ...scope, keyword, country, language });
      setAtlasResult(result); setMessage(`Atlas tìm thấy ${result.sub_niches_count} sub-niches, ${result.opportunities_count} opportunities. Chọn sub-niche để tạo research.`);
    } catch (err) { setError(String(err)); } finally { setBusy(false); }
  }

  async function loadSuggestions() {
    if (!keyword.trim()) return;
    setSuggestLoading(true);
    try {
      const result = await suggestKeywords({ keyword, country, language });
      setSuggestions(result.suggestions);
      setShowSuggestions(true);
    } catch (err) { setError(String(err)); } finally { setSuggestLoading(false); }
  }

  function useSuggestion(kw: string) {
    setKeyword(kw);
    setShowSuggestions(false);
  }

  async function approve() {
    if (!research || !selected) return;
    setBusy(true); setError('');
    try {
      const result = await approveResearch(research.research_run_id, selected.opportunity_id, scope);
      const run = await startRun({
        mode: 'production', channel_data_mode: 'none', ...scope,
        youtube_channel_id: channel.youtube_channel_id,
        flow_profile: channel.flow_profile,
        research_run_id: result.research_run_id,
      });
      setMessage('Đã tạo resource-pack run. Flow dừng trước bước gen media.');
      navigate(`/runs/${run.run_id}`);
    } catch (err) { setError(String(err)); } finally { setBusy(false); }
  }

  async function createFromAtlas() {
    if (atlasSelected.length === 0 || !atlasResult) return;
    setBusy(true); setError('');
    try {
      for (const sub of atlasSelected) {
        await startResearch({ ...scope, keyword: sub.keyword, country, language });
      }
      setMessage(`Đã tạo ${atlasSelected.length} research runs từ Atlas. Hãy mở từng run để approve.`);
      setAtlasSelected([]);
    } catch (err) { setError(String(err)); } finally { setBusy(false); }
  }

  const sourceEntries = Object.entries(research?.evidence ?? {});
  return (
    <div className="page research-page">
      <div className="research-hero">
        <div>
          <div className="research-kicker"><span className="pulse-dot" /> Market intelligence workspace</div>
          <h2>Find the gap before you build.</h2>
          <p>Research nhu cầu, cách đối thủ đang đóng gói chủ đề, rồi khóa một hướng resource pack cho đúng channel và thị trường.</p>
        </div>
        <div className="research-hero-mark">R<span>/</span>P</div>
      </div>
      <div className="research-steps"><span className={mode === 'standard' ? 'active' : ''}><b>01</b> Define market</span><i /><span className={(mode === 'standard' && research) || (mode === 'atlas' && atlasResult) ? 'active' : ''}><b>02</b> Read signals</span><i /><span className={selected ? 'active' : ''}><b>03</b> Lock production</span></div>

      <div className="panel research-input-panel">
        <div className="panel-heading"><div><h3>Set the research frame</h3><p>Channel hiện tại: <strong>{channel.title || channel.channel_id}</strong></p></div><span className="scope-chip">{scope.user_id} / {scope.channel_id}</span></div>

        <div className="research-mode-tabs">
          <button className={`mode-tab ${mode === 'standard' ? 'active' : ''}`} onClick={() => setMode('standard')}>
            <Search size={16} /> Standard
          </button>
          <button className={`mode-tab ${mode === 'atlas' ? 'active' : ''}`} onClick={() => setMode('atlas')}>
            <Compass size={16} /> Tube Atlas
          </button>
        </div>

        <div className="form-grid research-form-grid">
          <label>Market<select value={country} onChange={e => setCountry(e.target.value)}>{COUNTRIES.map(x => <option key={x.code} value={x.code}>{x.label} · {x.code}</option>)}</select></label>
          <label>Content language<select value={language} onChange={e => setLanguage(e.target.value)}>{LANGUAGES.map(x => <option key={x.code} value={x.code}>{x.label}</option>)}</select></label>
          <label className="keyword-field">
            Search keyword
            <input value={keyword} onChange={e => setKeyword(e.target.value)} placeholder="Ví dụ: tâm linh, tiền mã hóa, productivity" onBlur={() => setTimeout(() => setShowSuggestions(false), 200)} />
            {showSuggestions && suggestions.length > 0 && (
              <div className="suggestion-dropdown">
                {suggestions.slice(0, 10).map((s, i) => (
                  <button key={i} type="button" className="suggestion-item" onClick={() => useSuggestion(s.keyword)}>
                    <span className="suggestion-keyword">{s.keyword}</span>
                    <span className="suggestion-source">{s.source}</span>
                    {s.value && <span className="suggestion-value">+{s.value}%</span>}
                  </button>
                ))}
              </div>
            )}
            <div className="keyword-actions">
              {!suggestLoading && keyword.trim() && <button type="button" className="btn btn-ghost btn-sm" onClick={() => void loadSuggestions()}><Search size={14} />Gợi ý</button>}
              {suggestLoading && <span className="loading-sm"><RefreshCw size={14} className="spin" /></span>}
            </div>
          </label>

          {mode === 'standard' ? (
            <button className="btn btn-primary research-submit" disabled={busy || !keyword.trim()} onClick={() => void runResearch()}>
              {busy ? <><RefreshCw size={15} className="spin" />Researching</> : <><Search size={15} />Run research</>}
            </button>
          ) : (
            <button className="btn btn-primary research-submit" disabled={busy || !keyword.trim()} onClick={() => void runAtlasResearch()}>
              {busy ? <><RefreshCw size={15} className="spin" />Analyzing</> : <><Zap size={15} />Run Atlas</>}
            </button>
          )}
        </div>
      </div>
      {error && <div className="research-alert error-text"><AlertCircle size={16} />{error}</div>}
      {message && <div className="research-alert success"><CheckCircle2 size={16} />{message}</div>}

      {/* Standard Research Result */}
      {research && mode === 'standard' && <>
        <section className="research-signal-strip">
          <div className="signal-intro"><span className="signal-number">{research.opportunities.length}</span><div><strong>opportunity found</strong><small>for "{research.keyword}"</small></div></div>
          {sourceEntries.map(([source, item]) => <div className={`signal-source ${item.status === 'ok' ? 'ready' : 'missing'}`} key={source}><div className="signal-source-head"><span>{source.replace('_', ' ')}</span>{item.status === 'ok' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}</div><strong>{item.records?.length ?? 0}</strong><small>{item.status === 'ok' ? 'signals captured' : item.status}</small></div>)}
        </section>
        <div className="research-main-grid">
          <div className="panel opportunity-panel"><div className="panel-heading"><div><h3>Editorial opportunities</h3><p>Gap chỉ được approve khi có đủ tín hiệu độc lập và không còn blocking risk.</p></div><div className="research-actions"><button className="btn" disabled={logLoading} onClick={() => void loadLog()}>{logLoading ? 'Loading log…' : 'View run log'}</button><button className="btn btn-primary" disabled={busy || !selected} onClick={() => void approve()}><PlayCircle size={15} />Lock & create pack</button></div></div>
            {research.opportunities.map(opportunity => { const isOpen = expanded === opportunity.opportunity_id; const isSelected = selected?.opportunity_id === opportunity.opportunity_id; return <div className={`opportunity-card ${isSelected ? 'selected' : ''} ${opportunity.risk_flags.length ? 'blocked' : ''}`} key={opportunity.opportunity_id}><button type="button" className="opportunity-select" onClick={() => opportunity.risk_flags.length === 0 && setSelected(opportunity)} disabled={opportunity.risk_flags.length > 0}><div className="opportunity-card-top"><span className="opportunity-id">{opportunity.opportunity_id}</span><span className="score-pill">{opportunity.opportunity_score}<small>/100</small></span></div><h4>{opportunity.gap_statement}</h4><p>{opportunity.audience_moment}</p><div className="opportunity-meta"><span><strong>Angle</strong>{opportunity.editorial_angle}</span><span><strong>Evidence</strong>{opportunity.evidence_sources.join(', ') || 'none'}</span></div>{opportunity.risk_flags.length ? <div className="risk-line"><AlertCircle size={14} />Blocked: {opportunity.risk_flags.join(', ')}</div> : <div className="ready-line"><CheckCircle2 size={14} />Ready to lock for production</div>}</button><button className="expand-button" type="button" onClick={() => setExpanded(isOpen ? null : opportunity.opportunity_id)}><ChevronRight size={16} className={isOpen ? 'rotate-90' : ''} />{isOpen ? 'Hide evidence detail' : 'Inspect evidence detail'}</button>{isOpen && <div className="evidence-detail"><p><strong>Unserved question</strong>{opportunity.unserved_question}</p><p><strong>Promise</strong>{opportunity.promise}</p><p><strong>Coverage terms</strong>{opportunity.coverage_terms.join(' · ')}</p><pre>{JSON.stringify(opportunity.evidence_summary ?? {}, null, 2)}</pre></div>}</div>; })}
            {showLog && <div className="research-log-panel"><div className="research-log-heading"><div><h4>Research run log</h4><p>Nhật ký theo từng provider. Không ghi keyword thô hoặc bất kỳ credential nào.</p></div><button className="btn" onClick={() => setShowLog(false)}>Hide</button></div>{logEvents.length === 0 ? <div className="empty-state">Chưa có event log.</div> : <div className="research-log-list">{logEvents.map((event, index) => <div className={`research-log-event ${event.event.includes('failed') || event.event.includes('error') ? 'failure' : event.event.includes('unavailable') ? 'warning' : 'success'}`} key={`${event.timestamp}-${index}`}><time>{new Date(event.timestamp).toLocaleTimeString()}</time><strong>{event.event.replaceAll('_', ' ')}</strong><span>{event.provider ? `${event.provider} · ` : ''}{typeof event.record_count === 'number' ? `${event.record_count} records` : ''}{event.error_category ? ` · ${event.error_category}` : ''}</span>{event.error && <small>{event.error}</small>}</div>)}</div>}</div>}
          </div>
          <aside className="panel research-method-panel"><h3>What gets locked</h3><p>Approval creates the same resource-pack flow used by the Japanese channel, with the market evidence attached as its editorial source of truth.</p><div className="lock-list"><span><b>01</b> Topic & angle</span><span><b>02</b> Source directions</span><span><b>03</b> Psychology brief</span><span><b>04</b> Script & visual prompts</span><span><b>05</b> Publish draft</span></div><div className="manual-note"><strong>Manual after this point</strong><p>Gen ảnh, audio, Veo và ráp video vẫn do bạn chủ động chạy ở các màn hình riêng.</p></div></aside>
        </div>
      </>}

      {/* Tube Atlas Result */}
      {atlasResult && mode === 'atlas' && <>
        <section className="research-signal-strip atlas-summary">
          <div className="signal-intro"><span className="signal-number">{atlasResult.sub_niches_count}</span><div><strong>sub-niches discovered</strong><small>from "{atlasResult.seed_keyword}"</small></div></div>
          <div className="signal-source ready"><div className="signal-source-head"><span>SerpAPI</span><CheckCircle2 size={15} /></div><strong>{atlasResult.competitor_titles.length}</strong><small>competitor titles</small></div>
          <div className="signal-source ready"><div className="signal-source-head"><span>Google Trends</span><CheckCircle2 size={15} /></div><strong>{atlasResult.rising_queries.length}</strong><small>rising queries</small></div>
          <div className="signal-source ready"><div className="signal-source-head"><span>Related Questions</span><CheckCircle2 size={15} /></div><strong>{atlasResult.related_questions.length}</strong><small>questions</small></div>
        </section>
        <div className="research-main-grid">
          <div className="panel opportunity-panel"><div className="panel-heading"><div><h3>Tube Atlas: Sub-niches with demand signals</h3><p>Chọn các sub-niche có demand_score cao → Create research runs → Approve → Lock production.</p></div><div className="research-actions"><button className="btn btn-primary" disabled={busy || atlasSelected.length === 0} onClick={() => void createFromAtlas()}><PlayCircle size={15} />Create {atlasSelected.length} research runs</button></div></div>
            {atlasResult.top_sub_niches.map(sub => {
              const isSelected = atlasSelected.some(s => s.keyword === sub.keyword);
              return (
                <div className={`opportunity-card ${isSelected ? 'selected' : ''}`} key={sub.keyword}>
                  <button type="button" className="opportunity-select" onClick={() => setAtlasSelected(prev => isSelected ? prev.filter(s => s.keyword !== sub.keyword) : [...prev, sub])}>
                    <div className="opportunity-card-top">
                      <span className="opportunity-id">{sub.source}</span>
                      <span className="score-pill">{sub.demand_score}<small>/100</small></span>
                    </div>
                    <h4>{sub.keyword}</h4>
                    <p>{sub.unserved_question}</p>
                    <div className="opportunity-meta">
                      <span><strong>Angle</strong>{sub.angle}</span>
                      <span><strong>Competitors</strong>{sub.competitor_count} titles</span>
                      <span className="source-badge">{sub.source.replace('_', ' ')}</span>
                    </div>
                    <div className="promise-line">{sub.promise}</div>
                  </button>
                </div>
              );
            })}
          </div>
          <aside className="panel research-method-panel">
            <h3>Atlas Raw Data</h3>
            <details><summary>Competitor titles ({atlasResult.competitor_titles.length})</summary><ul>{atlasResult.competitor_titles.map((t, i) => <li key={i}>{t}</li>)}</ul></details>
            <details><summary>Rising queries ({atlasResult.rising_queries.length})</summary><ul>{atlasResult.rising_queries.map((q, i) => <li key={i}>{q}</li>)}</ul></details>
            <details><summary>Related questions ({atlasResult.related_questions.length})</summary><ul>{atlasResult.related_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></details>
            <div className="manual-note"><strong>Next step</strong><p>Chọn sub-niche → Create research runs → Mở từng run ở tab Standard để approve & lock production.</p></div>
          </aside>
        </div>
      </>}
    </div>
  );
}