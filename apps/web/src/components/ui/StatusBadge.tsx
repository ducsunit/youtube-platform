import { CheckCircle2, XCircle, Loader2, Clock, AlertCircle } from './Icons';
import { useT } from '../../i18n';

const KNOWN = ['pending', 'running', 'passed', 'complete', 'failed'];

export function StatusBadge({ status }: { status: string }) {
  const { t } = useT();
  const cls = KNOWN.includes(status) ? status : 'unknown';

  const renderIcon = () => {
    switch (status) {
      case 'complete':
      case 'passed':
        return <CheckCircle2 size={13} />;
      case 'failed':
        return <XCircle size={13} />;
      case 'running':
        return <Loader2 size={13} className="spin" />;
      case 'pending':
        return <Clock size={13} />;
      default:
        return <AlertCircle size={13} />;
    }
  };

  return (
    <span className={`badge badge-${cls}`}>
      {renderIcon()}
      <span>{t(`status.${status}`)}</span>
    </span>
  );
}
