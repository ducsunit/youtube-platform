import { useEffect, useState } from 'react';
import { Link2, Plus, RefreshCw, Save, Trash2, X, Sliders, RotateCw } from '../components/ui/Icons';
import { listChannels, registerChannel, updateChannel } from '../services/channelService';
import { reindexPlatform } from '../services/platformService';
import { useChannelContext } from '../contexts/ChannelContext';
import type { ChannelContext as Channel, RegisterChannelBody } from '../types';

const DEFAULT_USER_ID = 'dev-user';

export function ChannelsPage() {
  const { channels, currentChannel, selectChannel, reload: reloadContext } = useChannelContext();
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<RegisterChannelBody>({ user_id: DEFAULT_USER_ID, channel_id: '', youtube_channel_id: '', title: '', flow_profile: 'resource_pack' });
  const [title, setTitle] = useState('');
  const [flowProfile, setFlowProfile] = useState('resource_pack');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [allChannels, setAllChannels] = useState<Channel[]>(channels);
  const [reindexing, setReindexing] = useState(false);

  const load = async () => {
    setError(null);
    try {
      const result = await listChannels(DEFAULT_USER_ID, showInactive);
      setAllChannels(result.channels);
    } catch (e) { setError(String(e)); }
  };

  useEffect(() => { void load(); }, [showInactive]);
  useEffect(() => {
    if (!showInactive) setAllChannels(channels);
  }, [channels, showInactive]);

  const openCreate = () => {
    setEditing(null);
    setForm({ user_id: DEFAULT_USER_ID, channel_id: '', youtube_channel_id: '', title: '', flow_profile: 'resource_pack' });
    setError(null); setNotice(null); setShowForm(true);
  };

  const openEdit = (channel: Channel) => {
    setEditing(channel.channel_id);
    setTitle(channel.title ?? '');
    setFlowProfile(channel.flow_profile || 'resource_pack');
    setError(null); setNotice(null); setShowForm(true);
  };

  const save = async () => {
    setSaving(true); setError(null); setNotice(null);
    try {
      if (editing) {
        await updateChannel(editing, { user_id: DEFAULT_USER_ID, title, flow_profile: flowProfile });
        setNotice('Đã lưu thông tin channel.');
      } else {
        const result = await registerChannel({ ...form, title: form.title?.trim() || undefined });
        await reloadContext();
        selectChannel(result.channel.channel_id);
        setNotice('Đã đăng ký channel. Bước tiếp theo là kết nối YouTube ở trang Dữ liệu.');
      }
      await load();
      if (editing) await reloadContext();
      setShowForm(false);
    } catch (e) { setError(String(e)); }
    finally { setSaving(false); }
  };

  const setActive = async (channel: Channel, active: boolean) => {
    const label = channel.title || channel.channel_id;
    if (!active && !window.confirm(`Vô hiệu hóa channel “${label}”? Dữ liệu và run không bị xóa.`)) return;
    setError(null); setNotice(null);
    try {
      await updateChannel(channel.channel_id, { user_id: DEFAULT_USER_ID, active });
      await reloadContext(); await load();
      setNotice(active ? 'Đã bật lại channel.' : 'Đã vô hiệu hóa channel.');
    } catch (e) { setError(String(e)); }
  };

  const deactivate = async (channel: Channel) => setActive(channel, false);

  const reindex = async () => {
    if (!window.confirm('Reindex sẽ quét lại metadata của các run. Không chuyển ownership và không xóa file. Tiếp tục?')) return;
    setReindexing(true); setError(null); setNotice(null);
    try {
      const result = await reindexPlatform();
      setNotice(`Đã reindex ${result.indexed} run; bỏ qua ${result.skipped}; lỗi ${result.failures.length}.`);
    } catch (e) { setError(String(e)); }
    finally { setReindexing(false); }
  };

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <h2><Link2 size={21} style={{ marginRight: 8, color: 'var(--accent)' }} />Quản lý channel</h2>
          <div style={{ color: 'var(--muted)', fontSize: 13, marginTop: 5 }}>Đăng ký, chỉnh sửa và chọn channel cho toàn bộ workflow.</div>
        </div>
        <div className="spacer" />
        <label className="toolbar" style={{ fontSize: 12, color: 'var(--muted)' }}>
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Hiện channel đã tắt
        </label>
        <button type="button" className="btn" onClick={() => void load()}><RefreshCw size={14} /> Làm mới</button>
        <button type="button" className="btn btn-primary" onClick={openCreate}><Plus size={14} /> Thêm channel</button>
      </div>

      {error && <div className="error-text provider-alert">{error}</div>}
      {notice && <div className="success-text provider-alert">{notice}</div>}

      {showForm && (
        <section className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-title"><span>{editing ? 'Chỉnh sửa channel' : 'Đăng ký channel mới'}</span><span className="spacer" /><button type="button" className="btn btn-ghost" onClick={() => setShowForm(false)}><X size={15} /></button></div>
          <div className="panel-body">
            {!editing ? (
              <div className="provider-form-grid">
                <div className="form-row"><label htmlFor="channel-slug">Tên nội bộ</label><input id="channel-slug" value={form.channel_id} onChange={(e) => setForm({ ...form, channel_id: e.target.value })} placeholder="main" /></div>
                <div className="form-row"><label htmlFor="youtube-channel-id">YouTube Channel ID</label><input id="youtube-channel-id" value={form.youtube_channel_id} onChange={(e) => setForm({ ...form, youtube_channel_id: e.target.value })} placeholder="UC..." /></div>
                <div className="form-row"><label htmlFor="channel-title">Tên hiển thị</label><input id="channel-title" value={form.title ?? ''} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Main channel" /></div>
                <div className="form-row"><label htmlFor="channel-profile">Flow profile</label><input id="channel-profile" value={form.flow_profile ?? 'resource_pack'} onChange={(e) => setForm({ ...form, flow_profile: e.target.value })} /></div>
              </div>
            ) : (
              <div className="provider-form-grid">
                <div className="form-row"><label>YouTube Channel ID</label><input value={currentChannel?.channel_id === editing ? currentChannel.youtube_channel_id : ''} disabled /></div>
                <div className="form-row"><label htmlFor="edit-channel-title">Tên hiển thị</label><input id="edit-channel-title" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
                <div className="form-row"><label htmlFor="edit-channel-profile">Flow profile</label><input id="edit-channel-profile" value={flowProfile} onChange={(e) => setFlowProfile(e.target.value)} /></div>
              </div>
            )}
            <div className="toolbar" style={{ marginTop: 16 }}><button type="button" className="btn btn-primary" onClick={() => void save()} disabled={saving}><Save size={14} /> {saving ? 'Đang lưu…' : 'Lưu channel'}</button><button type="button" className="btn" onClick={() => setShowForm(false)} disabled={saving}>Hủy</button></div>
          </div>
        </section>
      )}

      {allChannels.length === 0 ? <div className="empty-state">{showInactive ? 'Không có channel đã tắt.' : 'Chưa có channel hợp lệ. Bấm “Thêm channel” để bắt đầu.'}</div> : (
        <div className="provider-grid">
          {allChannels.map((channel) => (
            <section className={`panel provider-card ${currentChannel?.channel_id === channel.channel_id ? 'channel-card-current' : ''}`} key={channel.channel_id}>
              <div className="panel-title"><span className="provider-dot" /><strong>{channel.title || channel.channel_id}</strong><span className={`provider-key-state ${channel.active !== false ? 'ok' : 'missing'}`}>{channel.active !== false ? 'Đang dùng' : 'Đã tắt'}</span></div>
              <div className="panel-body">
                <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.8 }}><div><strong>Tên nội bộ:</strong> <span className="mono">{channel.channel_id}</span></div><div><strong>YouTube:</strong> <span className="mono">{channel.youtube_channel_id}</span></div><div><strong>Profile:</strong> {channel.flow_profile}</div></div>
                <div className="toolbar" style={{ marginTop: 15 }}>
                  {channel.active !== false && <button type="button" className="btn btn-primary" onClick={() => selectChannel(channel.channel_id)} disabled={currentChannel?.channel_id === channel.channel_id}>{currentChannel?.channel_id === channel.channel_id ? 'Đang chọn' : 'Chọn channel'}</button>}
                  {channel.active === false ? (
                    <button type="button" className="btn btn-primary" onClick={() => void setActive(channel, true)}><RotateCw size={14} /> Bật lại</button>
                  ) : (
                    <>
                      <button type="button" className="btn" onClick={() => openEdit(channel)}><Sliders size={14} /> Sửa</button>
                      <button type="button" className="btn btn-ghost" onClick={() => void deactivate(channel)} style={{ color: 'var(--err)' }}><Trash2 size={14} /> Tắt</button>
                    </>
                  )}
                </div>
              </div>
            </section>
          ))}
        </div>
      )}

      <section className="panel provider-section" style={{ marginTop: 24 }}>
        <div className="panel-title"><Sliders size={16} /> Bảo trì hệ thống</div>
        <div className="panel-body"><p style={{ color: 'var(--muted)', fontSize: 13, marginTop: 0 }}>Dùng khi metadata trong SQLite không đồng bộ với các run trên đĩa. Reindex chỉ xây lại metadata.</p><button type="button" className="btn" onClick={() => void reindex()} disabled={reindexing}><RefreshCw size={14} className={reindexing ? 'spin' : ''} /> {reindexing ? 'Đang reindex…' : 'Rebuild run index'}</button></div>
      </section>
    </main>
  );
}
