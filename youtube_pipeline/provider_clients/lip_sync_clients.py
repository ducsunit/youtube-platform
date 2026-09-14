"""Lip-sync provider clients."""
from __future__ import annotations

import base64
import time
import logging
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger(__name__)


class BaseLipSyncClient:
    """Base class for lip-sync clients."""
    
    def lip_sync(self, video: bytes, audio: bytes, **params) -> bytes:
        raise NotImplementedError


class HedraClient(BaseLipSyncClient):
    """Hedra lip-sync client (5/day free tier)."""
    
    def __init__(self, api_key: str, base_url: str = "https://api.hedra.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=300.0,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )
        logger.info("HedraClient initialized")
    
    def _upload_video(self, video_bytes: bytes) -> str:
        """Upload video to Hedra, return asset ID."""
        resp = self.client.post(
            "/assets/video",
            files={"file": ("video.mp4", video_bytes, "video/mp4")},
            timeout=120.0
        )
        resp.raise_for_status()
        return resp.json()["asset_id"]
    
    def _upload_audio(self, audio_bytes: bytes) -> str:
        """Upload audio to Hedra, return asset ID."""
        resp = self.client.post(
            "/assets/audio",
            files={"file": ("audio.wav", audio_bytes, "audio/wav")},
            timeout=60.0
        )
        resp.raise_for_status()
        return resp.json()["asset_id"]
    
    def lip_sync(self, video: bytes, audio: bytes, **params) -> bytes:
        # 1. Upload video and audio
        video_asset_id = self._upload_video(video)
        audio_asset_id = self._upload_audio(audio)
        logger.info("Hedra assets uploaded | video=%s | audio=%s", video_asset_id, audio_asset_id)
        
        # 2. Create lip-sync job
        payload = {
            "video_asset_id": video_asset_id,
            "audio_asset_id": audio_asset_id,
            "model": params.get("model", "character-1"),
            "resolution": params.get("resolution", "720p"),
        }
        
        resp = self.client.post("/jobs/lip_sync", json=payload, timeout=60.0)
        resp.raise_for_status()
        job_id = resp.json()["job_id"]
        logger.info("Hedra lip-sync job started | job_id=%s", job_id)
        
        # 3. Poll for completion
        return self._poll_job(job_id)
    
    def _poll_job(self, job_id: str, timeout: int = 300) -> bytes:
        start = time.time()
        while time.time() - start < timeout:
            resp = self.client.get(f"/jobs/{job_id}", timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            
            if status == "completed":
                video_url = data["output_url"]
                video_resp = httpx.get(video_url, timeout=120.0, follow_redirects=True)
                video_resp.raise_for_status()
                logger.info("Hedra lip-sync completed | job_id=%s", job_id)
                return video_resp.content
            
            elif status == "failed":
                raise RuntimeError(f"Hedra lip-sync failed: {data.get('error', 'Unknown error')}")
            
            time.sleep(5)
        
        raise TimeoutError(f"Hedra lip-sync timed out")


class LivePortraitClient(BaseLipSyncClient):
    """LivePortrait lip-sync client (local, unlimited)."""
    
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=300.0)
        logger.info("LivePortraitClient initialized | base_url=%s", base_url)
    
    def _encode_video(self, video_bytes: bytes) -> str:
        import base64
        return base64.b64encode(video_bytes).decode()
    
    def _encode_audio(self, audio_bytes: bytes) -> str:
        import base64
        return base64.b64encode(audio_bytes).decode()
    
    def lip_sync(self, video: bytes, audio: bytes, **params) -> bytes:
        payload = {
            "video": self._encode_video(video),
            "audio": self._encode_audio(audio),
            "model": params.get("model", "liveportrait-v1"),
            "relative": params.get("relative", True),
            "paste_back": params.get("paste_back", True),
        }
        
        resp = self.client.post("/lip_sync", json=payload, timeout=120.0)
        resp.raise_for_status()
        result = resp.json()
        
        # Result is base64 encoded video
        import base64
        return base64.b64decode(result["video"])
    
    def health_check(self) -> bool:
        try:
            resp = self.client.get("/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False