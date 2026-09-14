"""Video generation provider clients."""
from __future__ import annotations

import json
import time
import logging
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger(__name__)


class BaseVideoClient:
    """Base class for video generation clients."""
    
    def generate(self, prompt: str, image: Optional[bytes] = None, **params) -> bytes:
        raise NotImplementedError


class KlingClient(BaseVideoClient):
    """Kling AI video generation client."""
    
    def __init__(self, api_key: str, base_url: str = "https://api.klingai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=300.0,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )
        logger.info("KlingClient initialized")
    
    def _upload_image(self, image_bytes: bytes) -> str:
        """Upload image to Kling, return image URL."""
        # Kling requires base64 or URL - using base64
        import base64
        b64 = base64.b64encode(image_bytes).decode()
        return f"data:image/png;base64,{b64}"
    
    def generate(self, prompt: str, image: Optional[bytes] = None, **params) -> bytes:
        duration = params.get("duration", 10)
        mode = params.get("mode", "std")
        
        # Prepare request
        payload = {
            "model_name": "kling-v1.6",
            "prompt": prompt,
            "duration": duration,
            "mode": mode,
            "cfg_scale": params.get("cfg_scale", 0.5),
        }
        
        if image:
            payload["image"] = self._upload_image(image)
            payload["image_tail"] = self._upload_image(image)  # same for start/end
        
        # 1. Submit task
        resp = self.client.post("/videos/image2video", json=payload, timeout=60.0)
        resp.raise_for_status()
        task_id = resp.json()["data"]["task_id"]
        logger.info("Kling task submitted | task_id=%s", task_id)
        
        # 2. Poll for completion
        return self._poll_task(task_id)
    
    def _poll_task(self, task_id: str, timeout: int = 300) -> bytes:
        start = time.time()
        while time.time() - start < timeout:
            resp = self.client.get(f"/videos/{task_id}", timeout=30.0)
            resp.raise_for_status()
            data = resp.json()["data"]
            status = data["task_status"]
            
            if status == "succeed":
                video_url = data["task_result"]["videos"][0]["url"]
                # Download video
                video_resp = httpx.get(video_url, timeout=120.0, follow_redirects=True)
                video_resp.raise_for_status()
                logger.info("Kling video generated | task_id=%s", task_id)
                return video_resp.content
            
            elif status == "failed":
                raise RuntimeError(f"Kling generation failed: {data.get('task_status_msg', 'Unknown error')}")
            
            time.sleep(5)
        
        raise TimeoutError(f"Kling generation timed out after {timeout}s")


class HailuoClient(BaseVideoClient):
    """Hailuo (Minimax) video generation client."""
    
    def __init__(self, api_key: str, base_url: str = "https://api.hailuo.ai/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=300.0,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )
        logger.info("HailuoClient initialized")
    
    def _upload_image(self, image_bytes: bytes) -> str:
        import base64
        b64 = base64.b64encode(image_bytes).decode()
        return f"data:image/png;base64,{b64}"
    
    def generate(self, prompt: str, image: Optional[bytes] = None, **params) -> bytes:
        duration = params.get("duration", 6)
        
        payload = {
            "model": "minimax-video-01",
            "prompt": prompt,
            "duration": duration,
        }
        
        if image:
            payload["image"] = self._upload_image(image)
        
        # 1. Submit task
        resp = self.client.post("/video/generate", json=payload, timeout=60.0)
        resp.raise_for_status()
        task_id = resp.json()["task_id"]
        logger.info("Hailuo task submitted | task_id=%s", task_id)
        
        return self._poll_task(task_id)
    
    def _poll_task(self, task_id: str, timeout: int = 300) -> bytes:
        start = time.time()
        while time.time() - start < timeout:
            resp = self.client.get(f"/video/status/{task_id}", timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            
            if status == "completed":
                video_url = data["video_url"]
                video_resp = httpx.get(video_url, timeout=120.0, follow_redirects=True)
                video_resp.raise_for_status()
                logger.info("Hailuo video generated | task_id=%s", task_id)
                return video_resp.content
            
            elif status == "failed":
                raise RuntimeError(f"Hailuo generation failed: {data.get('error', 'Unknown error')}")
            
            time.sleep(3)
        
        raise TimeoutError(f"Hailuo generation timed out")


class RunwayClient(BaseVideoClient):
    """Runway Gen-3 Alpha Turbo video generation client."""
    
    def __init__(self, api_key: str, base_url: str = "https://api.runwayml.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=300.0,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )
        logger.info("RunwayClient initialized")
    
    def _upload_image(self, image_bytes: bytes) -> str:
        # Runway expects direct upload to their storage
        resp = self.client.post(
            "/uploads",
            files={"file": ("image.png", image_bytes, "image/png")},
            timeout=60.0
        )
        resp.raise_for_status()
        return resp.json()["url"]
    
    def generate(self, prompt: str, image: Optional[bytes] = None, **params) -> bytes:
        duration = params.get("duration", 10)
        
        payload = {
            "model": "gen3a_turbo",
            "prompt": prompt,
            "duration": duration,
            "ratio": params.get("ratio", "1280:720"),
        }
        
        if image:
            payload["image"] = self._upload_image(image)
        
        # 1. Submit task
        resp = self.client.post("/image_to_video", json=payload, timeout=60.0)
        resp.raise_for_status()
        task_id = resp.json()["id"]
        logger.info("Runway task submitted | task_id=%s", task_id)
        
        return self._poll_task(task_id)
    
    def _poll_task(self, task_id: str, timeout: int = 300) -> bytes:
        start = time.time()
        while time.time() - start < timeout:
            resp = self.client.get(f"/tasks/{task_id}", timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            
            if status == "SUCCEEDED":
                video_url = data["output"][0]
                video_resp = httpx.get(video_url, timeout=120.0, follow_redirects=True)
                video_resp.raise_for_status()
                logger.info("Runway video generated | task_id=%s", task_id)
                return video_resp.content
            
            elif status == "FAILED":
                raise RuntimeError(f"Runway generation failed: {data.get('error', 'Unknown error')}")
            
            time.sleep(5)
        
        raise TimeoutError(f"Runway generation timed out")