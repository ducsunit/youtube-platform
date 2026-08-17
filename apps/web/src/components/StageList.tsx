import { AlertTriangle, RotateCw } from './Icons';
import { useT } from '../i18n';
import type { ActiveStage, StageRecord } from '../types';
import { StatusBadge } from './StatusBadge';

interface Props {
  stageOrder: string[];
  records: Record<string, StageRecord>;
  activeStage: ActiveStage | null;
}

/** Danh sách stage theo thứ tự thật (từ /api/config), nối thêm stage lạ nếu có. */
export function StageList({ stageOrder, records, activeStage }: Props) {
  const { t } = useT();

  const names = [...stageOrder];
  for (const name of Object.keys(records)) {
    if (!names.includes(name)) names.push(name);
  }

  return (
    <div style={{ maxHeight: 440, overflowY: 'auto' }}>
      {names.map((name, i) => {
        const rec = records[name];
        const status = rec ? rec.status : 'pending';
        const isRunning = activeStage?.name === name || status === 'running';
        const attempts = rec?.attempts ?? 1;
        const warnings = rec?.warnings?.length ?? 0;
        return (
          <div key={name} className={`stage-row${isRunning ? ' running' : ''}`}>
            <span className="stage-idx" style={isRunning ? { borderColor: 'var(--blue)', color: 'var(--blue)', background: 'rgba(59, 130, 246, 0.15)' } : undefined}>
              {i + 1}
            </span>
            <span className="stage-name">
              {t(`stage.${name}`)}
              {warnings > 0 && (
                <span className="chip" style={{ marginLeft: 8, color: 'var(--warn)', background: 'rgba(245, 158, 11, 0.15)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <AlertTriangle size={11} />
                  {warnings} {t('stages.warnings')}
                </span>
              )}
            </span>
            {attempts > 1 && (
              <span className="chip chip-count" title={t('stages.attempts')} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <RotateCw size={10} />
                +{attempts - 1} retry
              </span>
            )}
            <StatusBadge status={status} />
          </div>
        );
      })}
    </div>
  );
}

