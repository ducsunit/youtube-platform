import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  PlayCircle,
  Database,
  FileText,
  Sliders,
  Video,
  Sun,
  Moon,
  Globe,
  Activity,
  Sparkles
} from '../ui/Icons';
import { getConfig } from '../../api';
import { usePolling } from '../../hooks/usePolling';
import { useT } from '../../i18n';
import logoImg from '../../../logo.png';

export function Header() {
  const { lang, setLang, t } = useT();
  const location = useLocation();
  
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const saved = localStorage.getItem('theme');
    return (saved === 'light' || saved === 'dark') ? saved : 'dark';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const { data } = usePolling(() => getConfig(), {
    enabled: true,
    intervalMs: 30000,
  });

  let dotClass = 'status-dot off';
  let dotTitle = t('app.server');
  let statusLabel = t('app.server');

  if (data) {
    dotClass = data.busy ? 'status-dot warn' : 'status-dot ok';
    statusLabel = data.busy ? t('app.busy') : 'Live';
    dotTitle = data.busy ? `${t('app.server')} — ${t('app.busy')}` : `${t('app.server')} — Online`;
  }

  return (
    <header className="app-header">
      <Link to="/" className="header-brand">
        <img src={logoImg} alt="Logo" className="app-logo" />
        <span className="brand-title">
          {t('app.title')}
          <span className="badge-v3"><Sparkles size={11} /> V3</span>
        </span>
      </Link>

      <nav className="app-nav">
        <Link to="/" className={location.pathname === '/' ? 'active' : ''}>
          <PlayCircle size={16} />
          <span>{t('nav.runs')}</span>
        </Link>
        <Link to="/data" className={location.pathname === '/data' ? 'active' : ''}>
          <Database size={16} />
          <span>{t('nav.data')}</span>
        </Link>
        <Link to="/content" className={location.pathname === '/content' ? 'active' : ''}>
          <FileText size={16} />
          <span>{t('nav.content')}</span>
        </Link>
        <Link to="/build" className={location.pathname === '/build' ? 'active' : ''}>
          <Sliders size={16} />
          <span>{t('nav.build')}</span>
        </Link>
        <Link to="/video-gen" className={location.pathname === '/video-gen' ? 'active' : ''}>
          <Video size={16} />
          <span>{t('nav.videoGen')}</span>
        </Link>
      </nav>

      <div className="spacer" />

      <div className="status-pill" title={dotTitle}>
        <span className={dotClass} />
        <Activity size={13} className="status-icon-glow" />
        <span>{statusLabel}</span>
      </div>

      <div className="theme-toggle">
        <button
          type="button"
          className={theme === 'dark' ? 'active' : ''}
          onClick={() => setTheme('dark')}
          title="Dark Theme"
        >
          <Moon size={14} />
        </button>
        <button
          type="button"
          className={theme === 'light' ? 'active' : ''}
          onClick={() => setTheme('light')}
          title="Light Theme"
        >
          <Sun size={14} />
        </button>
      </div>

      <div className="lang-toggle">
        <button
          type="button"
          className={lang === 'vi' ? 'active' : ''}
          onClick={() => setLang('vi')}
        >
          <Globe size={13} /> VI
        </button>
        <button
          type="button"
          className={lang === 'en' ? 'active' : ''}
          onClick={() => setLang('en')}
        >
          EN
        </button>
      </div>
    </header>
  );
}
