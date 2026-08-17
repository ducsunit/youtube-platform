import { useEffect, useRef, useState } from 'react';
import { Terminal, Download, ArrowDownCircle, Copy, Check } from './Icons';
import { usePolling } from '../hooks/usePolling';
import { useT } from '../i18n';
import type { LogPage } from '../types';

interface Props {
  /** Hàm lấy trang log (run log hoặc data job log đều dùng được). */
  logFetcher: (offset: number, limit?: number) => Promise<LogPage>;
  /** URL tải log (nếu có) — hiện nút "Tải log". */
  downloadUrl?: string;
  running: boolean;
  intervalMs: number;
}

/**
 * Xem log theo kiểu paging stateless: mỗi lần poll dùng offset = next_offset
 * của lần trước. Dừng poll khi job xong VÀ đã đọc tới cuối file (eof).
 */
export function LogViewer({ logFetcher, downloadUrl, running, intervalMs }: Props) {
  const { t } = useT();
  const [lines, setLines] = useState<string[]>([]);
  const [eof, setEof] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [copied, setCopied] = useState(false);
  const offsetRef = useRef(0);
  const preRef = useRef<HTMLPreElement>(null);

  const { data } = usePolling(() => logFetcher(offsetRef.current), {
    enabled: running || !eof,
    intervalMs,
  });

  useEffect(() => {
    if (!data) return;
    offsetRef.current = data.next_offset;
    setEof(data.eof);
    if (data.lines.length > 0) {
      setLines((prev) => prev.concat(data.lines));
    }
  }, [data]);

  useEffect(() => {
    if (autoScroll && preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [lines, autoScroll]);

  const copyToClipboard = () => {
    if (lines.length === 0) return;
    navigator.clipboard.writeText(lines.join('\n'));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="panel">
      <div className="panel-title">
        <div className="toolbar" style={{ justifyContent: 'space-between', width: '100%' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Terminal size={16} style={{ color: 'var(--accent)' }} />
            <span>{t('log.title')}</span>
            {lines.length > 0 && (
              <span className="chip" style={{ fontSize: 11 }}>
                {lines.length} lines
              </span>
            )}
          </span>
          <div className="toolbar">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={copyToClipboard}
              disabled={lines.length === 0}
              style={{ padding: '4px 10px', fontSize: 12 }}
              title="Copy log to clipboard"
            >
              {copied ? <Check size={13} style={{ color: 'var(--ok)' }} /> : <Copy size={13} />}
              {copied ? 'Copied' : 'Copy'}
            </button>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />
              <ArrowDownCircle size={13} />
              {t('log.autoScroll')}
            </label>
            {downloadUrl && (
              <a className="btn btn-ghost" href={downloadUrl} download style={{ padding: '4px 10px', fontSize: 12 }}>
                <Download size={13} />
                {t('log.download')}
              </a>
            )}
          </div>
        </div>
      </div>
      <pre ref={preRef} className="log-viewer">
        {lines.length === 0
          ? eof
            ? t('log.noFile')
            : t('log.empty')
          : lines.join('\n')}
      </pre>
    </div>
  );
}

