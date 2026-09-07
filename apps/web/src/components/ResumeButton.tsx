import { useState } from 'react';
import { ApiError, resumeRun } from '../api';
import { useT } from '../i18n';

interface Props {
  runId: string;
  scope?: { user_id: string; channel_id: string };
  disabled?: boolean;
  onResumed: () => void;
}

/** Nút tiếp tục run: xác nhận rồi gọi POST /resume, báo lỗi 409 nếu bận. */
export function ResumeButton({ runId, scope, disabled, onResumed }: Props) {
  const { t } = useT();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const doResume = async () => {
    if (!window.confirm(`${t('runs.resume')}?`)) return;
    setWorking(true);
    setError(null);
    try {
      await resumeRun(runId, scope);
      onResumed();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(t('new.busy'));
      } else {
        setError(e instanceof ApiError ? String(e.detail) : String(e));
      }
    } finally {
      setWorking(false);
    }
  };

  return (
    <span>
      <button
        type="button"
        className="btn"
        onClick={() => void doResume()}
        disabled={disabled || working}
      >
        {t('runs.resume')}
      </button>
      {error && <span className="error-text" style={{ marginLeft: 8 }}>{error}</span>}
    </span>
  );
}
