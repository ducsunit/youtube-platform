import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Header } from './components/layout/Header';
import { Loader2 } from './components/ui/Icons';

const RunsPage = lazy(() => import('./pages/RunsPage').then(m => ({ default: m.RunsPage })));
const DataPage = lazy(() => import('./pages/DataPage').then(m => ({ default: m.DataPage })));
const BuildPage = lazy(() => import('./pages/BuildPage').then(m => ({ default: m.BuildPage })));
const VideoGenPage = lazy(() => import('./pages/VideoGenPage').then(m => ({ default: m.VideoGenPage })));
const ImageGenPage = lazy(() => import('./pages/ImageGenPage').then(m => ({ default: m.ImageGenPage })));
const AudioGenPage = lazy(() => import('./pages/AudioGenPage').then(m => ({ default: m.AudioGenPage })));
const JobsPage = lazy(() => import('./pages/JobsPage').then(m => ({ default: m.JobsPage })));
const CalendarPage = lazy(() => import('./pages/CalendarPage').then(m => ({ default: m.CalendarPage })));
const RunDetailPage = lazy(() => import('./pages/RunDetailPage').then(m => ({ default: m.RunDetailPage })));
const ModelConfigPage = lazy(() => import('./pages/ModelConfigPage').then(m => ({ default: m.ModelConfigPage })));
const ChannelsPage = lazy(() => import('./pages/ChannelsPage').then(m => ({ default: m.ChannelsPage })));

function PageFallback() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '350px', gap: '10px', color: 'var(--text-secondary)' }}>
      <Loader2 size={24} className="spin" />
      <span style={{ fontSize: '14px', fontWeight: 600 }}>Loading module...</span>
    </div>
  );
}

export default function App() {
  return (
    <>
      <Header />
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<RunsPage />} />
          <Route path="/data" element={<DataPage />} />
          <Route path="/build" element={<BuildPage />} />
          <Route path="/video-gen" element={<VideoGenPage />} />
          <Route path="/image-gen" element={<ImageGenPage />} />
          <Route path="/audio-gen" element={<AudioGenPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/settings/providers" element={<ModelConfigPage />} />
          <Route path="/channels" element={<ChannelsPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </>
  );
}
