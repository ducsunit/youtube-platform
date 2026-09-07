import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { LanguageProvider } from './i18n';
import { ChannelProvider } from './contexts/ChannelContext';
import './styles.css';
import './research.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <LanguageProvider>
        <ChannelProvider>
          <App />
        </ChannelProvider>
      </LanguageProvider>
    </BrowserRouter>
  </StrictMode>,
);
