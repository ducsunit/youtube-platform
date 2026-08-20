import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, Plus, RefreshCw, Save, Sliders } from '../components/Icons';
import { getModelConfig, updateModelConfig } from '../api';
import { useT } from '../i18n';
import type { ModelConfig, ModelProfileConfig, ModelProviderType } from '../types';

type DraftProfile = ModelProfileConfig & { api_key: string };

const roleLabels: Record<string, string> = {
  analysis: 'Analysis / research',
  writer: 'Writer',
  reviewer: 'Reviewer',
  editor: 'Editor / repair',
  auditor: 'Auditor',
  packaging: 'Packaging / visuals',
};

function toDraft(profile: ModelProfileConfig): DraftProfile {
  return { ...profile, api_key: '' };
}

function defaultProfile(): DraftProfile {
  return {
    provider: 'openai_compatible',
    model: 'gpt-4o-mini',
    base_url: 'https://api.openai.com/v1',
    api_key_env: 'OPENAI_API_KEY',
    api_key_configured: false,
    temperature: 0.2,
    max_output_tokens: 4096,
    api_key: '',
  };
}

export function ModelConfigPage() {
  const { t } = useT();
  const [config, setConfig] = useState<ModelConfig | null>(null);
  const [profiles, setProfiles] = useState<Record<string, DraftProfile>>({});
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await getModelConfig();
      setConfig(next);
      setProfiles(Object.fromEntries(Object.entries(next.profiles).map(([name, profile]) => [name, toDraft(profile)])));
      setRoles({ ...next.role_profiles });
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const profileNames = useMemo(() => Object.keys(profiles), [profiles]);

  const patchProfile = (name: string, patch: Partial<DraftProfile>) => {
    setProfiles((current) => ({ ...current, [name]: { ...current[name], ...patch } }));
    setSaved(false);
  };

  const addProfile = () => {
    const base = 'custom-provider';
    let name = base;
    let index = 2;
    while (profiles[name]) name = `${base}-${index++}`;
    setProfiles((current) => ({ ...current, [name]: defaultProfile() }));
    setSaved(false);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const next = await updateModelConfig({
        profiles: Object.fromEntries(Object.entries(profiles).map(([name, profile]) => [name, {
          provider: profile.provider,
          model: profile.model,
          base_url: profile.base_url,
          api_key_env: profile.api_key_env,
          api_key: profile.api_key,
          temperature: profile.temperature,
          max_output_tokens: profile.max_output_tokens,
        }])),
        role_profiles: roles,
      });
      setConfig(next);
      setProfiles(Object.fromEntries(Object.entries(next.profiles).map(([name, profile]) => [name, toDraft(profile)])));
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : t('providers.error'));
    } finally {
      setSaving(false);
    }
  };

  if (loading && !config) {
    return <main className="page"><div className="empty-state">{t('providers.refresh')}...</div></main>;
  }

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <h2><Sliders size={21} style={{ marginRight: 8, color: 'var(--accent)' }} />{t('providers.title')}</h2>
          <div style={{ color: 'var(--muted)', fontSize: 13, marginTop: 5 }}>{t('providers.desc')}</div>
        </div>
        <div className="spacer" />
        <button type="button" className="btn" onClick={() => void load()} disabled={loading || saving}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> {t('providers.refresh')}
        </button>
        <button type="button" className="btn btn-primary" onClick={() => void save()} disabled={saving || profileNames.length === 0}>
          <Save size={14} /> {saving ? t('providers.saving') : t('providers.save')}
        </button>
      </div>

      {error && <div className="error-text provider-alert"><AlertCircle size={15} /> {error}</div>}
      {saved && <div className="success-text provider-alert"><CheckCircle2 size={15} /> {t('providers.saved')}</div>}

      <section className="panel provider-section">
        <div className="panel-title"><Sliders size={16} /> {t('providers.roles')}</div>
        <div className="panel-body provider-role-grid">
          {(config?.roles ?? Object.keys(roles)).map((role) => (
            <div className="provider-role" key={role}>
              <label htmlFor={`role-${role}`}>{roleLabels[role] ?? role}</label>
              <select
                id={`role-${role}`}
                value={roles[role] ?? ''}
                onChange={(e) => { setRoles((current) => ({ ...current, [role]: e.target.value })); setSaved(false); }}
              >
                {profileNames.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </div>
          ))}
        </div>
      </section>

      <div className="provider-section-head">
        <div>
          <h3>{t('providers.profiles')}</h3>
          <p>{t('providers.security')}</p>
        </div>
        <button type="button" className="btn" onClick={addProfile}><Plus size={14} /> {t('providers.add')}</button>
      </div>

      <div className="provider-grid">
        {profileNames.map((name) => {
          const profile = profiles[name];
          const provider = profile.provider as ModelProviderType;
          return (
            <section className="panel provider-card" key={name}>
              <div className="panel-title">
                <span className="provider-dot" />
                <strong>{name}</strong>
                <span className={`provider-key-state ${profile.api_key_configured ? 'ok' : 'missing'}`}>
                  {profile.api_key_configured ? t('providers.configured') : t('providers.notConfigured')}
                </span>
              </div>
              <div className="panel-body">
                <div className="provider-form-grid">
                  <div className="form-row">
                    <label htmlFor={`${name}-provider`}>{t('providers.provider')}</label>
                    <select id={`${name}-provider`} value={provider} onChange={(e) => patchProfile(name, { provider: e.target.value as ModelProviderType })}>
                      {(config?.provider_types ?? ['gemini', 'openai_compatible']).map((type) => (
                        <option key={type} value={type}>{type === 'openai_compatible' ? 'OpenAI-compatible' : 'Gemini'}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-row">
                    <label htmlFor={`${name}-model`}>{t('providers.model')}</label>
                    <input id={`${name}-model`} type="text" value={profile.model} onChange={(e) => patchProfile(name, { model: e.target.value })} />
                  </div>
                  <div className="form-row provider-wide">
                    <label htmlFor={`${name}-base-url`}>{t('providers.baseUrl')}</label>
                    <input id={`${name}-base-url`} type="text" value={profile.base_url} onChange={(e) => patchProfile(name, { base_url: e.target.value })} />
                    {provider === 'openai_compatible' && <small>{t('providers.baseUrlHint')}</small>}
                  </div>
                  <div className="form-row provider-wide">
                    <label htmlFor={`${name}-key`}>{t('providers.apiKey')}</label>
                    <input id={`${name}-key`} type="password" value={profile.api_key} placeholder={profile.api_key_configured ? '••••••••  (configured)' : ''} onChange={(e) => patchProfile(name, { api_key: e.target.value })} autoComplete="new-password" />
                    <small>{t('providers.apiKeyHint')}</small>
                  </div>
                  <div className="form-row">
                    <label htmlFor={`${name}-env`}>{t('providers.apiKeyEnv')}</label>
                    <input id={`${name}-env`} type="text" value={profile.api_key_env} onChange={(e) => patchProfile(name, { api_key_env: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label htmlFor={`${name}-temperature`}>{t('providers.temperature')}</label>
                    <input id={`${name}-temperature`} type="number" min="0" max="2" step="0.1" value={profile.temperature} onChange={(e) => patchProfile(name, { temperature: Number(e.target.value) })} />
                  </div>
                  <div className="form-row">
                    <label htmlFor={`${name}-max-tokens`}>{t('providers.maxTokens')}</label>
                    <input id={`${name}-max-tokens`} type="number" min="1" step="1" value={profile.max_output_tokens ?? ''} onChange={(e) => patchProfile(name, { max_output_tokens: e.target.value ? Number(e.target.value) : null })} />
                  </div>
                </div>
              </div>
            </section>
          );
        })}
      </div>
    </main>
  );
}
