import { useEffect, useState } from 'react';
import { AlertTriangle, ChevronDown, RotateCw } from './Icons';
import { useT } from '../i18n';
import type { ActiveStage, StageRecord } from '../types';
import { StatusBadge } from './StatusBadge';

interface Props {
  stageOrder: string[];
  records: Record<string, StageRecord>;
  activeStage: ActiveStage | null;
}

type Phase = { key: string; stages: string[] };

// UI phases intentionally group the technical pipeline without changing its
// backend stage order or execution semantics.
const PHASES: Phase[] = [
  { key: 'research', stages: ['ingest', 'performance', 'topic_research', 'topic_candidates', 'topic_selection'] },
  { key: 'psychology', stages: ['source_lock', 'claim_ledger', 'narrative_brief'] },
  { key: 'script', stages: ['script_contract', 'planning', 'writing', 'review', 'consistency'] },
  { key: 'audit', stages: ['script_audit', 'script_qa', 'structure_check', 'psychology_format_check'] },
  { key: 'translation', stages: ['translate_script_vi', 'sections'] },
  { key: 'thumbnail', stages: ['thumbnail_contract'] },
  { key: 'visuals', stages: ['image_strategy', 'image_prompts'] },
  { key: 'delivery', stages: ['timeline', 'publish_draft', 'resource_pack', 'video_build'] },
];

const PHASE_STAGE_LABELS: Record<string, string> = {
  research: 'phases.research',
  psychology: 'phases.psychology',
  script: 'phases.script',
  audit: 'phases.audit',
  translation: 'phases.translation',
  thumbnail: 'phases.thumbnail',
  visuals: 'phases.visuals',
  delivery: 'phases.delivery',
};

function statusRank(status: string): number {
  return status === 'failed' ? 4 : status === 'running' ? 3 : status === 'passed' ? 2 : 1;
}

/** Danh sách stage theo thứ tự thật (từ /api/config), nối thêm stage lạ nếu có. */
export function StageList({ stageOrder, records, activeStage }: Props) {
  const { t } = useT();
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const allNames = [...stageOrder];
  for (const name of Object.keys(records)) {
    if (!allNames.includes(name)) allNames.push(name);
  }

  const grouped = new Set<string>();
  const phaseRows = PHASES.map((phase) => {
    const phaseNames = phase.stages.filter((name) => allNames.includes(name));
    phaseNames.forEach((name) => grouped.add(name));
    return { ...phase, names: phaseNames };
  }).filter((phase) => phase.names.length > 0);
  const ungrouped = allNames.filter((name) => !grouped.has(name));

  useEffect(() => {
    const active = activeStage?.name;
    if (!active) return;
    const phase = PHASES.find((item) => item.stages.includes(active));
    if (phase) setOpen((current) => ({ ...current, [phase.key]: true }));
  }, [activeStage?.name]);

  const renderStage = (name: string, index: number) => {
    const rec = records[name];
    const status = rec ? rec.status : 'pending';
    const isRunning = activeStage?.name === name || status === 'running';
    const attempts = rec?.attempts ?? 1;
    const warnings = rec?.warnings?.length ?? 0;
    return (
      <div key={name} className={`stage-row stage-detail-row${isRunning ? ' running' : ''}`}>
        <span className="stage-idx">{index + 1}</span>
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
            <RotateCw size={10} /> +{attempts - 1} retry
          </span>
        )}
        <StatusBadge status={status} />
      </div>
    );
  };

  return (
    <div style={{ maxHeight: 440, overflowY: 'auto' }}>
      {phaseRows.map((phase, phaseIndex) => {
        const statuses = phase.names.map((name) => records[name]?.status ?? 'pending');
        const passed = statuses.filter((status) => status === 'passed').length;
        const phaseStatus = statuses.reduce((best, status) => statusRank(status) > statusRank(best) ? status : best, 'pending');
        const isOpen = open[phase.key] ?? false;
        return (
          <div key={phase.key} className="stage-phase">
            <button type="button" className={`stage-phase-row${phaseStatus === 'running' ? ' running' : ''}`} onClick={() => setOpen((current) => ({ ...current, [phase.key]: !isOpen }))}>
              <span className="stage-idx stage-phase-idx">{phaseIndex + 1}</span>
              <span className="stage-phase-copy">
                <strong>{t(PHASE_STAGE_LABELS[phase.key])}</strong>
                <small>{passed}/{phase.names.length} {t('stages.complete')}</small>
              </span>
              <StatusBadge status={phaseStatus} />
              <ChevronDown size={15} className={`stage-chevron${isOpen ? ' open' : ''}`} />
            </button>
            {isOpen && <div className="stage-phase-details">{phase.names.map((name, index) => renderStage(name, index))}</div>}
          </div>
        );
      })}
      {ungrouped.length > 0 && <div className="stage-phase-details">{ungrouped.map((name, index) => renderStage(name, index))}</div>}
    </div>
  );
}
