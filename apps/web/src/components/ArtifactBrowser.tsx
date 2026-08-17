import { useEffect, useState } from 'react';
import { Folder, FolderOpen, FileText, Image as ImageIcon, Film, RefreshCw, FileCode, ChevronRight, ChevronDown } from './Icons';
import { getArtifactTree } from '../api';
import { usePolling } from '../hooks/usePolling';
import { useT } from '../i18n';
import type { ArtifactTree as ArtifactTreeType } from '../types';
import { humanSize } from '../utils';

interface Props {
  runId: string;
  running: boolean;
  intervalMs: number;
  selected: string | null;
  onSelect: (path: string) => void;
}

/** Cây thư mục artifact — thư mục mới tự mở rộng, thư mục đã thu gọn giữ nguyên. */
export function ArtifactBrowser({ runId, running, intervalMs, selected, onSelect }: Props) {
  const { t } = useT();
  const { data, refresh } = usePolling(
    () => getArtifactTree(runId),
    { enabled: running, intervalMs },
  );
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const tree: ArtifactTreeType = data?.tree ?? {};

  useEffect(() => {
    setExpanded((prev) => {
      const next = new Set(prev);
      let changed = false;
      for (const dir of Object.keys(tree)) {
        if (!next.has(dir)) {
          next.add(dir);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [tree]);

  const toggle = (dir: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(dir)) {
        next.delete(dir);
      } else {
        next.add(dir);
      }
      return next;
    });
  };

  const getFileIcon = (filename: string) => {
    const ext = filename.split('.').pop()?.toLowerCase();
    if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(ext || '')) {
      return <ImageIcon size={14} style={{ color: 'var(--blue)' }} />;
    }
    if (['mp4', 'webm', 'mov'].includes(ext || '')) {
      return <Film size={14} style={{ color: 'var(--accent)' }} />;
    }
    if (['json', 'yaml', 'yml'].includes(ext || '')) {
      return <FileCode size={14} style={{ color: 'var(--warn)' }} />;
    }
    return <FileText size={14} style={{ color: 'var(--text-secondary)' }} />;
  };

  const dirs = Object.keys(tree).sort();

  return (
    <div className="panel">
      <div className="panel-title">
        <div className="toolbar" style={{ justifyContent: 'space-between', width: '100%' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FolderOpen size={16} style={{ color: 'var(--accent)' }} />
            <span>{t('art.title')}</span>
          </span>
          <button type="button" className="btn btn-ghost" onClick={() => void refresh()} style={{ padding: '4px 10px', fontSize: 12 }}>
            <RefreshCw size={13} />
            {t('art.refresh')}
          </button>
        </div>
      </div>
      <div className="panel-body tree" style={{ maxHeight: 420, overflowY: 'auto', padding: 12 }}>
        {dirs.length === 0 && <div className="viewer-empty">{t('art.empty')}</div>}
        {dirs.map((dir) => {
          const files = tree[dir] ?? {};
          const names = Object.keys(files).sort();
          const isOpen = expanded.has(dir);
          const visible: string[] = isOpen ? names : [];
          return (
            <div key={dir || '(root)'} style={{ marginBottom: 4 }}>
              <div className="tree-dir" onClick={() => toggle(dir)}>
                <span className="arrow">{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
                {isOpen ? <FolderOpen size={15} style={{ color: 'var(--accent)' }} /> : <Folder size={15} style={{ color: 'var(--text-secondary)' }} />}
                <span>{dir || '(root)'}</span>
                <span style={{ color: 'var(--muted)', fontSize: 11 }}>({names.length})</span>
              </div>
              {visible.map((name) => {
                const path = dir ? `${dir}/${name}` : name;
                const info = files[name];
                return (
                  <div
                    key={path}
                    className={`tree-file${selected === path ? ' selected' : ''}`}
                    onClick={() => onSelect(path)}
                  >
                    {getFileIcon(name)}
                    <span>{name}</span>
                    {info.artifact_type && (
                      <span className="chip chip-count" style={{ fontSize: 10 }}>
                        {info.artifact_type}
                      </span>
                    )}
                    <span className="size">{humanSize(info.size_bytes)}</span>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

