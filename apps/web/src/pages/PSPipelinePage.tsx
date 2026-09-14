import { useState, useEffect, useCallback } from 'react';
import {
  startPSRun,
  listPSRuns,
  getPSRunStatus,
  listPSArtifacts,
  cancelPSRun,
  deletePSRun,
  connectPSPipelineEvents,
} from '../services/psPipelineService';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ArtifactViewer } from '../components/ArtifactViewer';
import { LogViewer } from '../components/LogViewer';
import { Header } from '../components/layout/Header';
import { StageList } from '../components/StageList';
import { ArtifactBrowser } from '../components/ArtifactBrowser';

export function PSPipelinePage() {
  const [runs, setRuns] = useState<PSRunListItem[]>([]);
  const [selectedRun, setSelectedRun] = useState<PSRunListItem | null>(null);
  const [runStatus, setRunStatus] = useState<PSRunStatus | null>(null);
  const [artifacts, setArtifacts] = useState<Record<string, { type: string; size_bytes: number; path: string }>>({});
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newTopic, setNewTopic] = useState('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [selectedArtifact, setSelectedArtifact] = useState<{ path: string; type: string } | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [logOffset, setLogOffset] = useState(0);

  // Load runs on mount
  useEffect(() => {
    loadRuns();
  }, []);

  const loadRuns = async () => {
    try {
      const data = await listPSRuns();
      setRuns(data.runs || []);
    } catch (error) {
      console.error('Failed to load runs:', error);
    }
  };

  const pollRunStatus = useCallback(async (runId: string) => {
    try {
      const status = await getPSRunStatus(runId);
      setRunStatus(status);
    } catch (error) {
      console.error('Failed to get run status:', error);
    }
  }, []);

  useEffect(() => {
    if (selectedRun && selectedRun.status === 'running') {
      const interval = setInterval(() => pollRunStatus(selectedRun.run_id), 2000);
      return () => clearInterval(interval);
    }
  }, [selectedRun, pollRunStatus]);

  useEffect(() => {
    if (selectedRun) {
      loadArtifacts(selectedRun.run_id);
    }
  }, [selectedRun]);

  const loadArtifacts = async (runId: string) => {
    try {
      const data = await listPSArtifacts(runId);
      setArtifacts(data.artifacts || {});
    } catch (error) {
      console.error('Failed to load artifacts:', error);
    }
  };

  const handleCreateRun = async () => {
    if (!newTopic.trim()) return;
    setCreating(true);
    try {
      const response = await startPSRun({
        topic: newTopic,
        mode: 'production',
      });
      setShowCreateDialog(false);
      setNewTopic('');
      // Select the new run
      setTimeout(() => {
        setSelectedRun({ run_id: response.run_id, topic: newTopic, status: 'starting', created_at: '', updated_at: '', progress_percent: 0 });
      }, 1000);
    } catch (error) {
      console.error('Failed to create run:', error);
      alert('Failed to create run: ' + (error as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const handleSelectRun = (run: PSRunListItem) => {
    setSelectedRun(run);
    pollRunStatus(run.run_id);
  };

  const handleCancelRun = async (runId: string) => {
    if (!confirm('Cancel this pipeline run?')) return;
    try {
      await cancelPSRun(runId);
      await loadRuns();
      if (selectedRun?.run_id === runId) {
        setRunStatus(null);
        setSelectedRun(null);
      }
    } catch (error) {
      alert('Failed to cancel: ' + (error as Error).message);
    }
  };

  const handleDeleteRun = async (runId: string) => {
    if (!confirm('Delete this run and all its artifacts? This cannot be undone.')) return;
    try {
      await deletePSRun(runId);
      await loadRuns();
      if (selectedRun?.run_id === runId) {
        setRunStatus(null);
        setSelectedRun(null);
      }
    } catch (error) {
      alert('Failed to delete: ' + (error as Error).message);
    }
  };

  const handleViewArtifact = (path: string, type: string) => {
    setSelectedArtifact({ path, type });
  };

  const stageOrder = [
    'psychology_brief_v2',
    'contract_v2',
    'shot_list',
    'script_writing_v2',
    'review_v2',
    'character_ref_gen',
    'image_batch_gen',
    'thumbnail_gen',
    'animation_gen',
    'lip_sync_gen',
    'voiceover_gen',
    'video_edit',
    'shorts_pipeline',
  ];

  const stageLabels: Record<string, string> = {
    psychology_brief_v2: 'Psychology Brief',
    contract_v2: 'Contract',
    shot_list: 'Shot List',
    script_writing_v2: 'Script Writing',
    review_v2: 'Review',
    character_ref_gen: 'Character Ref',
    image_batch_gen: 'Image Batch',
    thumbnail_gen: 'Thumbnail',
    animation_gen: 'Animation',
    lip_sync_gen: 'Lip Sync',
    voiceover_gen: 'Voiceover',
    video_edit: 'Video Edit',
    shorts_pipeline: 'Shorts Pipeline',
  };

  if (!selectedRun) {
    return (
      <div className="ps-pipeline-page">
        <Header title="Problem-Solving Pipeline" />
        <div className="ps-pipeline-container">
          <div className="ps-sidebar">
            <div className="ps-header">
              <h2>Problem-Solving Pipeline</h2>
              <button className="btn-primary" onClick={() => setShowCreateDialog(true)}>
                + New Run
              </button>
            </div>
            <div className="runs-list">
              {runs.length === 0 ? (
                <p className="empty-state">No runs yet. Create your first pipeline run.</p>
              ) : (
                <ul>
                  {runs.map((run) => (
                    <li
                      key={run.run_id}
                      className={`run-item ${selectedRun?.run_id === run.run_id ? 'active' : ''}`}
                      onClick={() => handleSelectRun(run)}
                    >
                      <div className="run-info">
                        <div className="run-topic">{run.topic}</div>
                        <div className="run-meta">
                          <StatusBadge status={run.status} />
                          <span>{run.progress_percent}%</span>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          <div className="ps-empty-state">
            <div className="empty-icon">🎬</div>
            <h3>Select a run or create new</h3>
            <p>Start a new problem-solving pipeline or select an existing run to view progress.</            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ps-pipeline-page">
      <Header title="Problem-Solving Pipeline" />
      <div className="ps-pipeline-container">
        <div className="ps-sidebar">
          <div className="ps-header">
            <h2>Problem-Solving Pipeline</h2>
            <button className="btn-primary" onClick={() => setShowCreateDialog(true)}>
              + New Run
            </button>
          </div>
          <div className="runs-list">
            <ul>
              {runs.map((run) => (
                <li
                  key={run.run_id}
                  className={`run-item ${selectedRun?.run_id === run.run_id ? 'active' : ''}`}
                  onClick={() => handleSelectRun(run)}
                >
                  <div className="run-info">
                    <div className="run-topic">{run.topic}</div>
                    <div className="run-meta">
                      <StatusBadge status={run.status} />
                      <span>{run.progress_percent}%</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="ps-main">
          <div className="ps-header-bar">
            <h3>{selectedRun.topic}</h3>
            <div className="header-actions">
              <StatusBadge status={runStatus?.status || selectedRun.status} size="lg" />
              {runStatus?.status === 'running' && (
                <button className="btn-danger" onClick={() => cancelPSRun(selectedRun.run_id)}>
                  Cancel
                </button>
              )}
              <button className="btn-danger" onClick={() => deleteRun(selectedRun.run_id)}>
                Delete
              </button>
            </div>
          </div>

          <div className="ps-progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${runStatus?.progress_percent || selectedRun.progress_percent}%` }}
            />
            <span>{runStatus?.progress_percent ?? selectedRun.progress_percent}%</span>
          </div>

          {runStatus?.message && (
            <div className="ps-message">{runStatus.message}</div>
          )}

          <div className="ps-tabs">
            <button className="tab-btn active">Stages</button>
            <button className="tab-btn">Artifacts</button>
            <button className="tab-btn">Logs</button>
          </div>

          <div className="ps-content">
            {/* Stages Tab */}
            <div className="stage-list">
              {stageOrder.map((stageKey) => {
                const status = runStatus?.stage_progress?.[stageKey] || 'pending';
                return (
                  <div key={stageKey} className={`stage-item ${status}`}>
                    <div className="stage-info">
                      <span className="stage-icon">
                        {status === 'completed' ? '✓' : status === 'running' ? '⟳' : '○'}
                      </span>
                      <span className="stage-name">{stageLabels[stageKey] || stageKey}</span>
                    </div>
                    <StatusBadge status={status} size="sm" />
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    );
  }
}

// Need to import types
interface PSRunListItem {
  run_id: string;
  topic: string;
  status: string;
  created_at: string;
  updated_at: string;
  progress_percent: number;
}

interface PSRunStatus {
  run_id: string;
  status: string;
  current_stage?: string;
  stage_progress: Record<string, string>;
  artifacts_ready: Record<string, boolean>;
  progress_percent: number;
  message: string;
  updated_at: string;
}