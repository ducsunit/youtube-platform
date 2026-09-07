import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  PlayCircle,
  Database,
  Search,
  Sliders,
  Video,
  Sun,
  Moon,
  Globe,
  Activity,
  Sparkles,
  Link2,
} from '../ui/Icons';
import { getConfig } from '../../api';
import { usePolling } from '../../hooks/usePolling';
import { useT } from '../../i18n';
import { useChannelContext } from '../../contexts/ChannelContext';
import logoImg from '../../../logo.png';

export function Header() {
  const { lang, setLang, t } = useT();
  const location = useLocation();
  const { channels, currentChannel, loading: channelsLoading, error: channelsError, selectChannel } = useChannelContext();
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const saved = localStorage.getItem('theme');
    return (saved === 'light' || saved === 'dark') ? saved : 'dark';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const channelScope = currentChannel ? { user_id: currentChannel.user_id, channel_id: currentChannel.channel_id } : null;
  const { data } = usePolling(() => (channelScope ? getConfig(channelScope) : Promise.resolve(null)), { enabled: channelScope !== null, intervalMs: 30000 });
  const dotClass = data ? (data.busy ? 'status-dot warn' : 'status-dot ok') : 'status-dot off';
  const statusLabel = data ? (data.busy ? t('app.busy') : 'Live') : t('app.server');

  return (
    <header className="app-header">
      <Link to="/" className="header-brand"><img src={logoImg} alt="Logo" className="app-logo" /><span className="brand-title">{t('app.title')}<span className="badge-v3"><Sparkles size={11} /> V3</span></span></Link>
      <nav className="app-nav">
        <Link to="/" className={location.pathname === '/' ? 'active' : ''}><PlayCircle size={16} /><span>{t('nav.runs')}</span></Link>
        <Link to="/data" className={location.pathname === '/data' ? 'active' : ''}><Database size={16} /><span>{t('nav.data')}</span></Link>
        <Link to="/research" className={location.pathname === '/research' ? 'active' : ''}><Search size={16} /><span>Research</span></Link>
        <Link to="/build" className={location.pathname === '/build' ? 'active' : ''}><Sliders size={16} /><span>{t('nav.build')}</span></Link>
        <Link to="/video-gen" className={location.pathname === '/video-gen' ? 'active' : ''}><Video size={16} /><span>{t('nav.videoGen')}</span></Link>
        <Link to="/image-gen" className={location.pathname === '/image-gen' ? 'active' : ''}><Sparkles size={16} /><span>{t('nav.imageGen')}</span></Link>
        <Link to="/channels" className={location.pathname === '/channels' ? 'active' : ''}><Link2 size={16} /><span>{t('nav.channels')}</span></Link>
        <Link to="/settings/providers" className={location.pathname.startsWith('/settings') ? 'active' : ''}><Sliders size={16} /><span>{t('nav.providers')}</span></Link>
      </nav>
      <div className="spacer" />
      <div className="channel-selector" title={channelsError ? 'Unable to load channels' : undefined}>
        <label htmlFor="channel-select">Channel</label>
        {channelsLoading ? <span className="channel-selector-state">Loading…</span> : channels.length === 0 ? <Link to="/channels" className="channel-selector-state">Add channel</Link> : (
          <select id="channel-select" value={currentChannel?.channel_id ?? ''} onChange={(event) => selectChannel(event.target.value)} aria-label="Current channel">
            {channels.map((channel) => <option key={channel.channel_id} value={channel.channel_id}>{channel.title || channel.channel_id}</option>)}
          </select>
        )}
      </div>
      <div className="status-pill" title={statusLabel}><span className={dotClass} /><Activity size={13} className="status-icon-glow" /><span>{statusLabel}</span></div>
      <div className="theme-toggle"><button type="button" className={theme === 'dark' ? 'active' : ''} onClick={() => setTheme('dark')} title="Dark Theme"><Moon size={14} /></button><button type="button" className={theme === 'light' ? 'active' : ''} onClick={() => setTheme('light')} title="Light Theme"><Sun size={14} /></button></div>
      <div className="lang-toggle"><button type="button" className={lang === 'vi' ? 'active' : ''} onClick={() => setLang('vi')}><Globe size={13} /> VI</button><button type="button" className={lang === 'en' ? 'active' : ''} onClick={() => setLang('en')}>EN</button></div>
    </header>
  );
}
