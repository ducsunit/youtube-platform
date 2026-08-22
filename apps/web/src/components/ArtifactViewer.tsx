import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Eye, Download, Copy, Check, FileText } from './Icons';
import { ApiError, artifactUrl, getArtifactText } from '../api';
import { useT } from '../i18n';

interface Props {
  runId: string;
  path: string | null;
}

type Kind = 'json' | 'text' | 'image' | 'audio' | 'video' | 'binary';

const TEXT_EXTS = ['txt', 'md', 'srt', 'tsv', 'csv', 'vtt'];
const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif'];
const AUDIO_EXTS = ['mp3', 'wav', 'm4a', 'aac', 'ogg'];
const VIDEO_EXTS = ['mp4', 'mov', 'webm'];

function kindOf(path: string): Kind {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  if (ext === 'json') return 'json';
  if (TEXT_EXTS.includes(ext)) return 'text';
  if (IMAGE_EXTS.includes(ext)) return 'image';
  if (AUDIO_EXTS.includes(ext)) return 'audio';
  if (VIDEO_EXTS.includes(ext)) return 'video';
  return 'binary';
}

/** Xem nội dung artifact: JSON/text dạng pre, ảnh/audio/video inline, còn lại tải về. */
export function ArtifactViewer({ runId, path }: Props) {
  const { t } = useT();
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!path) return;
    const kind = kindOf(path);
    if (kind !== 'json' && kind !== 'text') {
      setText(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setText(null);
    setError(null);
    getArtifactText(runId, path)
      .then((value) => {
        if (!cancelled) setText(value);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [runId, path]);

  const copyText = () => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!path) {
    return (
      <div className="panel">
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Eye size={16} style={{ color: 'var(--accent)' }} />
            <span>{t('art.title')}</span>
          </span>
        </div>
        <div className="viewer-empty">
          {t('art.empty')}
        </div>
      </div>
    );
  }

  const kind = kindOf(path);
  const downloadHref = artifactUrl(runId, path, true);
  // Thumbnail prompts are meant to be copied verbatim into an image model.
  // Do not visually truncate their long style/identity/negative-prompt tail.
  const isFullCopyPrompt = /(^|\/)(thumbnail-prompt(?:-text)?|.*-prompt)\.txt$/i.test(path);

  let body: ReactNode = null;
  if (error) {
    const msg =
      error.status === 413
        ? t('art.tooLarge')
        : error.status === 404
          ? t('art.notFound')
          : `${t('art.loadError')} (HTTP ${error.status})`;
    body = (
      <div className="viewer-empty">
        {msg}
        <div style={{ marginTop: 12 }}>
          <a className="btn btn-primary" href={downloadHref} download>
            <Download size={14} />
            {t('art.download')}
          </a>
        </div>
      </div>
    );
  } else if (kind === 'json' || kind === 'text') {
    body = (
      <pre
        className="log-viewer"
        style={isFullCopyPrompt ? { maxHeight: 'none', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } : { maxHeight: 420 }}
        data-kind={kind}
      >
        {text ?? '…'}
      </pre>
    );
  } else if (kind === 'image') {
    body = (
      <div style={{ textAlign: 'center', padding: 12 }}>
        <img className="preview-img" src={artifactUrl(runId, path)} alt={path} style={{ maxHeight: 380 }} />
      </div>
    );
  } else if (kind === 'audio') {
    body = (
      <div style={{ padding: 20 }}>
        <audio controls src={artifactUrl(runId, path)} style={{ width: '100%' }}>
          <a href={downloadHref} download>
            <Download size={14} />
            {t('art.download')}
          </a>
        </audio>
      </div>
    );
  } else if (kind === 'video') {
    body = (
      <div style={{ textAlign: 'center', padding: 12 }}>
        <video controls src={artifactUrl(runId, path)} style={{ maxWidth: '100%', maxHeight: 380, borderRadius: 10 }}>
          <a href={downloadHref} download>
            <Download size={14} />
            {t('art.download')}
          </a>
        </video>
      </div>
    );
  } else {
    body = (
      <div className="viewer-empty">
        {t('art.binary')}
        <div style={{ marginTop: 12 }}>
          <a className="btn btn-primary" href={downloadHref} download>
            <Download size={14} />
            {t('art.download')}
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-title">
        <div className="toolbar" style={{ justifyContent: 'space-between', width: '100%' }}>
          <span className="mono" style={{ textTransform: 'none', letterSpacing: 0, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
            <FileText size={15} style={{ color: 'var(--accent)' }} />
            {path}
          </span>
          <div className="toolbar">
            {(kind === 'json' || kind === 'text') && text && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={copyText}
                style={{ padding: '4px 10px', fontSize: 12 }}
              >
                {copied ? <Check size={13} style={{ color: 'var(--ok)' }} /> : <Copy size={13} />}
                {copied ? 'Đã copy toàn bộ' : isFullCopyPrompt ? 'Copy full prompt' : 'Copy'}
              </button>
            )}
            <a className="btn btn-ghost" href={downloadHref} download style={{ padding: '4px 10px', fontSize: 12 }}>
              <Download size={13} />
              {t('art.download')}
            </a>
          </div>
        </div>
      </div>
      <div className="panel-body">{body}</div>
    </div>
  );
}
