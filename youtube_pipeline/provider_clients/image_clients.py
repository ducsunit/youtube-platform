"""ComfyUI client for image generation with IP-Adapter FaceID."""
from __future__ import annotations

import json
import uuid
import time
import logging
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)


class ComfyUIClient:
    """ComfyUI client for IP-Adapter FaceID workflows."""
    
    def __init__(self, base_url: str = "http://localhost:8188", workflows_dir: str = "./workflows"):
        self.base_url = base_url.rstrip("/")
        self.workflows_dir = Path(workflows_dir)
        self.client = httpx.Client(base_url=self.base_url, timeout=300.0)
        logger.info("ComfyUIClient initialized | base_url=%s | workflows_dir=%s", self.base_url, self.workflows_dir)
    
    def _load_workflow(self, workflow_name: str) -> Dict[str, Any]:
        path = self.workflows_dir / f"{workflow_name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Workflow not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _upload_image(self, image_bytes: bytes, filename: str = "input.png") -> str:
        """Upload image to ComfyUI, return image name."""
        files = {"image": (filename, image_bytes, "image/png")}
        resp = self.client.post("/upload/image", files=files, timeout=60.0)
        resp.raise_for_status()
        return resp.json()["name"]
    
    def _queue_prompt(self, prompt: Dict[str, Any]) -> str:
        """Queue prompt, return prompt_id."""
        resp = self.client.post("/prompt", json={"prompt": prompt, "client_id": str(uuid.uuid4())}, timeout=30.0)
        resp.raise_for_status()
        return resp.json()["prompt_id"]
    
    def _wait_for_completion(self, prompt_id: str, timeout: int = 300) -> List[str]:
        """Wait for execution, return list of output filenames."""
        start = time.time()
        while time.time() - start < timeout:
            resp = self.client.get(f"/history/{prompt_id}", timeout=10.0)
            if resp.status_code == 200:
                history = resp.json()
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    images = []
                    for node_id, node_output in outputs.items():
                        for img in node_output.get("images", []):
                            images.append(img["filename"])
                    if images:
                        return images
            time.sleep(2)
        raise TimeoutError(f"ComfyUI generation timed out after {timeout}s")
    
    def _download_image(self, filename: str, subfolder: str = "", type: str = "output") -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": type}
        resp = self.client.get("/view", params=params, timeout=60.0)
        resp.raise_for_status()
        return resp.content
    
    def generate_with_workflow(
        self, 
        workflow_name: str, 
        inputs: Dict[str, Any], 
        reference_image: Optional[bytes] = None
    ) -> List[bytes]:
        """Execute workflow with inputs, return list of image bytes."""
        workflow = self._load_workflow(workflow_name)
        
        # Upload reference image if provided
        ref_image_name = None
        if reference_image:
            ref_image_name = self._upload_image(reference_image, "ref.png")
        
        # Inject inputs into workflow nodes
        for node_id, node in workflow.items():
            inputs_dict = node.get("inputs", {})
            
            # Handle reference image input
            if "reference_image" in inputs_dict and reference_image:
                inputs_dict["reference_image"] = ref_image_name or ""
            
            # Handle image input for img2img
            if "image" in inputs_dict and reference_image:
                inputs_dict["image"] = ref_image_name or ""
            
            # Inject text prompts and parameters
            for key, value in inputs.items():
                if key in inputs_dict:
                    inputs_dict[key] = value
                
                # Also check for nested params
                if "params" in inputs_dict and isinstance(inputs_dict["params"], dict):
                    if key in inputs_dict["params"]:
                        inputs_dict["params"][key] = value
        
        prompt_id = self._queue_prompt(workflow)
        output_filenames = self._wait_for_completion(prompt_id)
        
        # Download all outputs
        results = []
        for fname in output_filenames:
            results.append(self._download_image(fname))
        return results
    
    def generate_character_ref(self, reference_image: bytes, prompt: str = "") -> bytes:
        """Generate master character reference (1024x1024)."""
        default_prompt = (
            "chalk-line figure, anonymous adult Japanese silhouette, simple off-white ink lines, "
            "round unfeatured head, restrained dot eyes, slim neutral body, black charcoal clothing blocks, "
            "white background, high contrast, 16:9, masterpiece, best quality"
        )
        results = self.generate_with_workflow(
            "ipadapter_faceid_char_ref",
            {"prompt": prompt or default_prompt},
            reference_image=reference_image
        )
        return results[0] if results else b""
    
    def generate_batch(self, reference_image: bytes, prompts: List[str], **params) -> List[bytes]:
        """Batch generate with same character reference."""
        all_results = []
        batch_size = params.get("batch_size", 4)
        
        for i in range(0, len(prompts), batch_size):
            batch = prompts[i:i+batch_size]
            for p in batch:
                results = self.generate_with_workflow(
                    "ipadapter_faceid_batch",
                    {"shot_prompt": p},
                    reference_image=reference_image
                )
                all_results.extend(results)
        
        return all_results
    
    def generate_thumbnail(self, reference_image: bytes, prompt: str) -> List[bytes]:
        """Generate thumbnail options A/B (1280x720)."""
        return self.generate_with_workflow(
            "ipadapter_faceid_thumbnail",
            {"thumbnail_prompt": prompt},
            reference_image=reference_image
        )
    
    def health_check(self) -> bool:
        """Check if ComfyUI is reachable."""
        try:
            resp = self.client.get("/system_stats", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False