import { useCallback, useEffect, useState } from 'react';
import { Loader2, Plus, RefreshCw, Save, X } from '../components/Icons';
import { getChannel, getTtsVoices, listChannels, previewTtsVoice, saveChannel } from '../api';
import type { ChannelInfo, VoiceCharacter } from '../types';

const CHANNEL_ID_RE = /^[A-Za-z0-9._-]{1,64}$/;
const HEX_RE = /^#[0-9a-fA-F]{6}$/;

interface CatalogRow {
  title: string;
  url: string;
  supports: string;
}

interface ProfileState {
  display_name: string;
  language: string;
  owner: string;
  youtubeIdsText: string;
  competitorPatterns: string;
  competitorDna: string;
  competitorUpdated: string;
  frameworksText: string;
  aliasesText: string;
  catalog: CatalogRow[];
  characterBible: string;
  characterStyleLock: string;
  compositionLock: string;
  typographyLock: string;
  textColor: string;
  accentColor: string;
  backgroundColor: string;
  ttsSpeaker: string;
  ttsSpeed: string;
  ttsIntonation: string;
}

const EMPTY_PROFILE: ProfileState = {
  display_name: '',
  language: 'ja',
  owner: '',
  youtubeIdsText: '',
  competitorPatterns: '',
  competitorDna: '',
  competitorUpdated: '',
  frameworksText: '',
  aliasesText: '',
  catalog: [],
  characterBible: '',
  characterStyleLock: '',
  compositionLock: '',
  typographyLock: '',
  textColor: '',
  accentColor: '',
  backgroundColor: '',
  ttsSpeaker: '21',
  ttsSpeed: '1',
  ttsIntonation: '0.85',
};

function hydrate(raw: Record<string, unknown>): ProfileState {
  const competitor = (raw.competitor ?? {}) as Record<string, unknown>;
  const claims = (raw.claims ?? {}) as Record<string, unknown>;
  const sources = (raw.sources ?? {}) as Record<string, unknown>;
  const locks = (raw.style_locks ?? {}) as Record<string, unknown>;
  const aliases = (claims.framework_source_aliases ?? {}) as Record<string, unknown>;
  const aliasesLines = Object.entries(aliases)
    .map(([term, list]) => `${term}: ${Array.isArray(list) ? list.join(', ') : String(list)}`)
    .join('\n');
  const ids = Array.isArray(raw.youtube_channel_ids) ? raw.youtube_channel_ids.map(String) : [];
  return {
    ...EMPTY_PROFILE,
    display_name: String(raw.display_name ?? ''),
    language: String(raw.language ?? 'ja'),
    owner: String(raw.owner ?? ''),
    youtubeIdsText: ids.join(', '),
    competitorPatterns: String(competitor.patterns ?? ''),
    competitorDna: String(competitor.writing_dna ?? ''),
    competitorUpdated: String(competitor.last_updated ?? ''),
    frameworksText: Array.isArray(claims.known_named_frameworks)
      ? claims.known_named_frameworks.map(String).join('\n')
      : '',
    aliasesText: aliasesLines,
    catalog: Array.isArray(sources.approved_catalog)
      ? sources.approved_catalog.map((row) => ({
          title: String((row as Record<string, unknown>).title ?? ''),
          url: String((row as Record<string, unknown>).url ?? ''),
          supports: String((row as Record<string, unknown>).supports ?? ''),
        }))
      : [],
    characterBible: String(locks.CHARACTER_BIBLE ?? ''),
    characterStyleLock: String(locks.CHARACTER_STYLE_LOCK ?? ''),
    compositionLock: String(locks.THUMBNAIL_COMPOSITION_LOCK ?? ''),
    typographyLock: String(locks.THUMBNAIL_TYPOGRAPHY_LOCK ?? ''),
    textColor: String(locks.text_color ?? ''),
    accentColor: String(locks.accent_color ?? ''),
    backgroundColor: String(locks.background_color ?? ''),
    ttsSpeaker: String((raw.tts as Record<string, unknown> | undefined)?.speaker ?? '21'),
    ttsSpeed: String((raw.tts as Record<string, unknown> | undefined)?.speed_scale ?? '1'),
    ttsIntonation: String((raw.tts as Record<string, unknown> | undefined)?.intonation_scale ?? '0.85'),
  };
}

/** Form -> profile JSON. Section rỗng bị bỏ hẳn để kênh dùng built-in defaults. */
function serialize(state: ProfileState): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    schema_version: 1,
    display_name: state.display_name.trim(),
    language: state.language,
  };
  const ids = state.youtubeIdsText.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);
  if (ids.length) payload.youtube_channel_ids = ids;
  if (state.owner.trim()) payload.owner = state.owner.trim();

  const patterns = state.competitorPatterns.trim();
  const dna = state.competitorDna.trim();
  const updated = state.competitorUpdated.trim();
  if (patterns || dna || updated) {
    payload.competitor = {
      ...(patterns ? { patterns } : {}),
      ...(dna ? { writing_dna: dna } : {}),
      ...(updated ? { last_updated: updated } : {}),
    };
  }

  const frameworks = state.frameworksText.split('\n').map((s) => s.trim()).filter(Boolean);
  const aliases: Record<string, string[]> = {};
  for (const line of state.aliasesText.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const sep = trimmed.indexOf(':');
    if (sep <= 0) continue;
    const term = trimmed.slice(0, sep).trim();
    const values = trimmed
      .slice(sep + 1)
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    if (term && values.length) aliases[term] = values;
  }
  if (frameworks.length || Object.keys(aliases).length) {
    payload.claims = {
      ...(frameworks.length ? { known_named_frameworks: frameworks } : {}),
      ...(Object.keys(aliases).length ? { framework_source_aliases: aliases } : {}),
    };
  }

  const catalog = state.catalog
    .map((row) => ({
      title: row.title.trim(),
      url: row.url.trim(),
      supports: row.supports.trim(),
    }))
    .filter((row) => row.title && row.url);
  if (catalog.length) payload.sources = { approved_catalog: catalog };

  const locks: Record<string, string> = {};
  for (const [key, value] of Object.entries({
    CHARACTER_BIBLE: state.characterBible,
    CHARACTER_STYLE_LOCK: state.characterStyleLock,
    THUMBNAIL_COMPOSITION_LOCK: state.compositionLock,
    THUMBNAIL_TYPOGRAPHY_LOCK: state.typographyLock,
    text_color: state.textColor,
    accent_color: state.accentColor,
    background_color: state.backgroundColor,
  })) {
    const v = String(value).trim();
    if (v) locks[key] = v;
  }
  if (Object.keys(locks).length) payload.style_locks = locks;

  const speakerNum = parseInt(state.ttsSpeaker, 10);
  if (!Number.isNaN(speakerNum)) {
    payload.tts = {
      speaker: speakerNum,
      ...(state.ttsSpeed !== '' ? { speed_scale: parseFloat(state.ttsSpeed) } : {}),
      ...(state.ttsIntonation !== '' ? { intonation_scale: parseFloat(state.ttsIntonation) } : {}),
    };
  }

  return payload;
}

interface SectionProps {
  title: string;
  hint?: string;
  children: React.ReactNode;
}

function Section({ title, hint, children }: SectionProps) {
  return (
    <section className="panel mb-4 p-4">
      <h3 className="text-sm font-bold text-heading">{title}</h3>
      {hint && <p className="mt-1 mb-3 text-[11px] leading-relaxed text-muted">{hint}</p>}
      {children}
    </section>
  );
}

const labelCls = 'block text-xs font-semibold text-secondary mb-1.5';

export function ChannelsPage() {
  const [channels, setChannels] = useState<ChannelInfo[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [profile, setProfile] = useState<ProfileState>(EMPTY_PROFILE);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newId, setNewId] = useState('');
  const [mode, setMode] = useState<'form' | 'json'>('form');
  const [jsonText, setJsonText] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ttsVoices, setTtsVoices] = useState<{ available: boolean; voices: VoiceCharacter[] } | null>(null);
  const [previewing, setPreviewing] = useState(false);

  useEffect(() => {
    getTtsVoices()
      .then((data) => setTtsVoices(data))
      .catch(() => setTtsVoices({ available: false, voices: [] }));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await listChannels();
      setChannels(data.channels ?? []);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const patch = (changes: Partial<ProfileState>) =>
    setProfile((prev) => ({ ...prev, ...changes }));

  const openEditor = useCallback(async (channelId: string) => {
    setSelectedId(channelId);
    setMessage(null);
    setError(null);
    setMode('form');
    setLoadingProfile(true);
    try {
      const profileData = await getChannel(channelId);
      setProfile(hydrate(profileData as Record<string, unknown>));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingProfile(false);
    }
  }, []);

  const toggleMode = () => {
    if (mode === 'json') {
      try {
        const parsed = JSON.parse(jsonText) as Record<string, unknown>;
        setProfile(hydrate(parsed));
        setMode('form');
        setError(null);
      } catch (e) {
        setError(`JSON không hợp lệ, chưa thể quay lại form: ${e instanceof Error ? e.message : String(e)}`);
      }
    } else {
      setJsonText(JSON.stringify(serialize(profile), null, 2));
      setMode('json');
    }
  };

  const save = async () => {
    if (!selectedId) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      let payload: Record<string, unknown>;
      if (mode === 'json') {
        payload = JSON.parse(jsonText) as Record<string, unknown>;
      } else {
        payload = serialize(profile);
      }
      payload.channel_id = selectedId;
      await saveChannel(selectedId, payload);
      setMessage(`Đã lưu "${selectedId}" vào config/channels/${selectedId}/profile.json`);
      await refresh();
      if (mode === 'json') setJsonText(JSON.stringify(payload, null, 2));
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const createChannel = async () => {
    const channelId = newId.trim();
    if (!CHANNEL_ID_RE.test(channelId)) {
      setError('Channel ID chỉ gồm A-Z a-z 0-9 . _ - (tối đa 64 ký tự).');
      return;
    }
    setCreating(true);
    setError(null);
    try {
      await saveChannel(channelId, { schema_version: 1, channel_id: channelId });
      await refresh();
      await openEditor(channelId);
      setNewId('');
      setMessage(`Đã tạo kênh "${channelId}". Điền form rồi bấm Lưu.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  };

  const updateCatalogRow = (index: number, changes: Partial<CatalogRow>) =>
    setProfile((prev) => ({
      ...prev,
      catalog: prev.catalog.map((row, i) => (i === index ? { ...row, ...changes } : row)),
    }));

  const colorField = (label: string, key: 'textColor' | 'accentColor' | 'backgroundColor') => {
    const value = profile[key];
    const validHex = HEX_RE.test(value);
    return (
      <div>
        <label className={labelCls}>{label}</label>
        <div className="flex items-center gap-2">
          <input
            type="color"
            value={validHex ? value.toLowerCase() : '#000000'}
            onChange={(e) => patch({ [key]: e.target.value.toUpperCase() })}
            aria-label={`${label} picker`}
            className="h-8 w-10 shrink-0 cursor-pointer rounded-md border border-line bg-transparent p-0.5"
          />
          <input
            type="text"
            value={value}
            placeholder="#FFE500"
            onChange={(e) => patch({ [key]: e.target.value })}
          />
        </div>
      </div>
    );
  };

  const previewVoice = async () => {
    setPreviewing(true);
    try {
      const blob = await previewTtsVoice({
        speaker: parseInt(profile.ttsSpeaker, 10) || 21,
        speed_scale: parseFloat(profile.ttsSpeed) || 1,
        intonation_scale: parseFloat(profile.ttsIntonation) || 0.85,
      });
      void new Audio(URL.createObjectURL(blob)).play();
    } catch (e) {
      setError(String(e));
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Kênh</h2>
          <p className="mt-0.5 text-[13px] text-muted">
            Mỗi kênh một profile riêng: đối thủ, nguồn dẫn chiếu, claim policy và style lock. Lưu form sẽ tự sinh profile.json.
          </p>
        </div>
        <div className="spacer" />
        <button type="button" className="btn" onClick={() => void refresh()}>
          <RefreshCw size={14} />
          Làm mới
        </button>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(280px,340px)_minmax(0,1fr)]">
        {/* CỘT TRÁI */}
        <aside className="flex flex-col gap-4 lg:sticky lg:top-[84px]">
          <div className="panel p-4">
            <div className="mb-3 text-sm font-bold text-heading">Danh sách kênh</div>
            {channels === null ? (
              <div className="text-[13px] text-muted">Đang tải...</div>
            ) : channels.length === 0 ? (
              <div className="text-[13px] text-muted">Chưa có kênh nào.</div>
            ) : (
              <div className="flex flex-col gap-2">
                {channels.map((c) => (
                  <button
                    key={c.channel_id}
                    type="button"
                    onClick={() => void openEditor(c.channel_id)}
                    disabled={loadingProfile}
                    className={`block w-full rounded-xl border px-3 py-2.5 text-left transition duration-150 hover:-translate-y-px disabled:opacity-50 ${
                      selectedId === c.channel_id
                        ? 'border-accent bg-accent/10 shadow-md shadow-accent/20'
                        : 'border-line hover:border-accent hover:bg-panel-hover'
                    }`}
                  >
                    <div className={`truncate text-[13.5px] font-semibold ${c.valid === false ? 'text-err' : 'text-heading'}`}>
                      {c.display_name}
                      {c.valid === false && <span className="ml-1.5" title={c.error}>⚠</span>}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-muted">
                      {c.channel_id} · {c.has_overrides ? 'có override' : 'built-in defaults'}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="panel p-4">
            <div className="mb-2.5 text-sm font-bold text-heading">Tạo kênh mới</div>
            <input
              type="text"
              placeholder="channel-id (A-Z a-z 0-9 . _ -)"
              value={newId}
              onChange={(e) => setNewId(e.target.value)}
              className="mb-2"
            />
            <button
              type="button"
              className="btn btn-primary w-full justify-center"
              onClick={() => void createChannel()}
              disabled={creating || !newId.trim()}
            >
              {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Tạo kênh
            </button>
          </div>
        </aside>

        {/* CỘT PHẢI */}
        <main>
          {!selectedId ? (
            <div className="panel empty-state">Chọn một kênh ở bên trái hoặc tạo kênh mới.</div>
          ) : loadingProfile ? (
            <div className="panel empty-state">
              <Loader2 size={16} className="animate-spin" /> Đang tải...
            </div>
          ) : (
            <>
              <div className="panel mb-4 flex flex-wrap items-center gap-2.5 p-4">
                <span className="text-[15px] font-bold text-heading">{profile.display_name || selectedId}</span>
                <span className="text-xs text-muted">{selectedId}</span>
                <div className="spacer" />
                <div className="radio-row m-0">
                  <label className={mode === 'form' ? 'sel' : ''}>
                    <input type="radio" name="editor-mode" checked={mode === 'form'} onChange={() => mode === 'json' && toggleMode()} />
                    Form
                  </label>
                  <label className={mode === 'json' ? 'sel' : ''}>
                    <input type="radio" name="editor-mode" checked={mode === 'json'} onChange={() => mode === 'form' && toggleMode()} />
                    JSON
                  </label>
                </div>
                <button type="button" className="btn btn-primary" onClick={() => void save()} disabled={saving}>
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  Lưu
                </button>
              </div>

              {mode === 'json' ? (
                <section className="panel mb-4 p-4">
                  <p className="mb-2 text-[11px] leading-relaxed text-muted">
                    Chỉnh trực tiếp profile.json. Bấm "Form" để parse ngược lại — lỗi JSON sẽ giữ nguyên chế độ này.
                  </p>
                  <textarea
                    value={jsonText}
                    onChange={(e) => setJsonText(e.target.value)}
                    spellCheck={false}
                    className="min-h-[420px] w-full resize-y rounded-lg border border-line bg-base px-3 py-2.5 font-mono text-xs leading-relaxed text-content focus:border-accent focus:outline-none"
                  />
                </section>
              ) : (
                <>
                  <Section title="1. Thông tin chung">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                      <div>
                        <label className={labelCls}>Tên hiển thị</label>
                        <input type="text" value={profile.display_name} onChange={(e) => patch({ display_name: e.target.value })} />
                      </div>
                      <div>
                        <label className={labelCls}>Ngôn ngữ nội dung</label>
                        <select value={profile.language} onChange={(e) => patch({ language: e.target.value })}>
                          <option value="ja">ja — Nhật</option>
                          <option value="vi">vi — Việt</option>
                          <option value="en">en — Anh</option>
                        </select>
                      </div>
                      <div>
                        <label className={labelCls}>Owner (dành cho đa người dùng sau này)</label>
                        <input type="text" value={profile.owner} placeholder="email / username" onChange={(e) => patch({ owner: e.target.value })} />
                      </div>
                    </div>
                    <label className={labelCls + ' mt-3'}>YouTube Channel IDs (phân tách bởi dấu phẩy)</label>
                    <input
                      type="text"
                      value={profile.youtubeIdsText}
                      placeholder="UCxxxxxxxxxxxxxxxxxxxxxx, UCyyyyyyyyyyyyyyyyyyyyyy"
                      onChange={(e) => patch({ youtubeIdsText: e.target.value })}
                    />
                    <p className="mt-1 text-[11px] leading-snug text-muted">
                      Giúp tự dò đúng profile khi tạo run từ dataset của kênh này.
                    </p>
                  </Section>

                  <Section
                    title="2. Competitor intelligence"
                    hint="Grammar của kênh đối thủ trong cùng ngách: cách đặt title, nhịp mở đầu, cấu trúc revelation. Inject vào các prompt khi chạy run."
                  >
                    <label className={labelCls}>Competitor patterns</label>
                    <textarea
                      className="min-h-[90px]"
                      value={profile.competitorPatterns}
                      onChange={(e) => patch({ competitorPatterns: e.target.value })}
                      placeholder="## Competitor: ..."
                    />
                    <label className={labelCls + ' mt-2.5'}>Writing DNA</label>
                    <textarea
                      className="min-h-[90px]"
                      value={profile.competitorDna}
                      onChange={(e) => patch({ competitorDna: e.target.value })}
                      placeholder="- Open with... - Return an ordinary symbol..."
                    />
                    <label className={labelCls + ' mt-2.5'}>Cập nhật lần cuối</label>
                    <input type="date" value={profile.competitorUpdated} onChange={(e) => patch({ competitorUpdated: e.target.value })} />
                  </Section>

                  <Section
                    title="3. Claim policy"
                    hint="Thuật ngữ lý thuyết mặc định bị chặn nếu source pack không chặn rõ. Kênh khác niche nên thay bằng thuật ngữ riêng."
                  >
                    <label className={labelCls}>Named frameworks (mỗi dòng một thuật ngữ)</label>
                    <textarea
                      className="min-h-[64px]"
                      value={profile.frameworksText}
                      onChange={(e) => patch({ frameworksText: e.target.value })}
                      placeholder={'ユング心理学\n個性化\nシャドウ'}
                    />
                    <label className={labelCls + ' mt-2.5'}>Source aliases (mỗi dòng: thuật ngữ: alias1, alias2)</label>
                    <textarea
                      className="min-h-[64px]"
                      value={profile.aliasesText}
                      onChange={(e) => patch({ aliasesText: e.target.value })}
                      placeholder={'シャドウ: shadow, ユング, jung\n個性化: individuation, jung'}
                    />
                  </Section>

                  <Section
                    title="4. Nguồn dẫn chiếu được phép (approved catalog)"
                    hint="Ranh giới claim safety: chỉ được khóa source từ danh sách này."
                  >
                    {profile.catalog.map((row, index) => (
                      <div key={index} className="mb-2 grid grid-cols-1 items-center gap-2 md:grid-cols-[1fr_1.2fr_1.4fr_auto]">
                        <input type="text" value={row.title} placeholder="Title" onChange={(e) => updateCatalogRow(index, { title: e.target.value })} />
                        <input type="text" value={row.url} placeholder="https://..." onChange={(e) => updateCatalogRow(index, { url: e.target.value })} />
                        <input type="text" value={row.supports} placeholder="Supports cái gì" onChange={(e) => updateCatalogRow(index, { supports: e.target.value })} />
                        <button
                          type="button"
                          className="btn btn-ghost justify-center"
                          onClick={() => setProfile((prev) => ({ ...prev, catalog: prev.catalog.filter((_, i) => i !== index) }))}
                          aria-label="Xóa nguồn"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      className="btn"
                      onClick={() => setProfile((prev) => ({ ...prev, catalog: [...prev.catalog, { title: '', url: '', supports: '' }] }))}
                    >
                      <Plus size={14} />
                      Thêm nguồn
                    </button>
                  </Section>

                  <Section
                    title="5. Style lock (visual identity)"
                    hint="Nhận diện hình ảnh cố định cho mọi thumbnail và visual của kênh."
                  >
                    <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
                      {colorField('Màu headline', 'textColor')}
                      {colorField('Màu accent duy nhất', 'accentColor')}
                      {colorField('Màu nền overlay', 'backgroundColor')}
                    </div>
                    <label className={labelCls}>CHARACTER_BIBLE</label>
                    <textarea className="min-h-[56px]" value={profile.characterBible} onChange={(e) => patch({ characterBible: e.target.value })} />
                    <label className={labelCls + ' mt-2.5'}>CHARACTER_STYLE_LOCK</label>
                    <textarea className="min-h-[56px]" value={profile.characterStyleLock} onChange={(e) => patch({ characterStyleLock: e.target.value })} />
                    <label className={labelCls + ' mt-2.5'}>THUMBNAIL_COMPOSITION_LOCK</label>
                    <textarea className="min-h-[56px]" value={profile.compositionLock} onChange={(e) => patch({ compositionLock: e.target.value })} />
                    <label className={labelCls + ' mt-2.5'}>THUMBNAIL_TYPOGRAPHY_LOCK</label>
                    <textarea className="min-h-[56px]" value={profile.typographyLock} onChange={(e) => patch({ typographyLock: e.target.value })} />
                  </Section>

                  <Section
                    title="6. Giọng đọc (VOICEVOX)"
                    hint={
                      ttsVoices?.available
                        ? 'Giọng local miễn phí — stage tts_generate sẽ đọc toàn bộ script bằng giọng này khi chạy run.'
                        : `VOICEVOX engine offline (${ttsVoices ? 'không kết nối được' : '?'}). Bật app VOICEVOX (port 50021) rồi bấm Làm mới để xem danh sách giọng. Vẫn lưu được setting để chạy sau.`
                    }
                  >
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      <div className="sm:col-span-2">
                        <label className={labelCls}>Giọng mặc định cho kênh</label>
                        <select value={profile.ttsSpeaker} onChange={(e) => patch({ ttsSpeaker: e.target.value })}>
                          {!ttsVoices?.available && <option value={profile.ttsSpeaker}>ID {profile.ttsSpeaker} (engine offline)</option>}
                          {(ttsVoices?.voices ?? []).map((v) =>
                            v.styles.map((st) => (
                              <option key={st.id} value={st.id}>
                                {v.character} — {st.name} ({st.id})
                              </option>
                            )),
                          )}
                        </select>
                      </div>
                      <div>
                        <label className={labelCls}>Tốc độ (speedScale)</label>
                        <input type="number" step="0.05" min="0.5" max="2" value={profile.ttsSpeed}
                               onChange={(e) => patch({ ttsSpeed: e.target.value })} />
                      </div>
                    </div>
                    <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
                      <div>
                        <label className={labelCls}>Ngữ điệu (intonationScale)</label>
                        <input type="number" step="0.05" min="0.3" max="1.6" value={profile.ttsIntonation}
                               onChange={(e) => patch({ ttsIntonation: e.target.value })} />
                      </div>
                      <div className="flex items-end">
                        <button type="button" className="btn w-full justify-center"
                                onClick={() => void previewVoice()} disabled={previewing || !ttsVoices?.available}>
                          {previewing ? <Loader2 size={14} className="animate-spin" /> : null}
                          Nghe thử
                        </button>
                      </div>
                    </div>
                  </Section>
                </>
              )}
            </>
          )}
        </main>
      </div>

      {message && (
        <div className="mt-3.5 rounded-[10px] border border-ok/30 bg-ok/10 px-3.5 py-2.5 text-[13px] text-ok">
          {message}
        </div>
      )}
      {error && (
        <div className="msg-banner msg-err">{error}</div>
      )}
    </div>
  );
}
