"""Audio/TTS provider clients."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx
import edge_tts

logger = logging.getLogger(__name__)


class BaseAudioClient:
    """Base class for audio generation clients."""
    
    def synthesize(self, text: str, voice: str, **params) -> bytes:
        raise NotImplementedError
    
    def batch_synthesize(self, segments: List[Dict]) -> Dict[str, bytes]:
        raise NotImplementedError


class VoicevoxClient(BaseAudioClient):
    """Voicevox TTS client (local engine)."""
    
    def __init__(self, base_url: str = "http://localhost:50021", default_speaker: int = 8):
        self.base_url = base_url.rstrip("/")
        self.default_speaker = default_speaker
        self.client = httpx.Client(base_url=self.base_url, timeout=60.0)
        logger.info("VoicevoxClient initialized | base_url=%s | default_speaker=%d", base_url, default_speaker)
    
    def _audio_query(self, text: str, speaker: int, params: Dict) -> Dict:
        resp = self.client.post("/audio_query", params={"text": text, "speaker": speaker}, timeout=30.0)
        resp.raise_for_status()
        query = resp.json()
        
        # Apply custom params
        for k in ["speed_scale", "pitch_scale", "intonation_scale", "volume_scale", "pre_phoneme_length", "post_phoneme_length"]:
            if k in params:
                query[k] = params[k]
        return query
    
    def synthesize(self, text: str, voice: str = "speaker_8", **params) -> bytes:
        speaker = int(voice.replace("speaker_", "")) if voice.startswith("speaker_") else int(voice) if voice.isdigit() else self.default_speaker
        query = self._audio_query(text, speaker, params)
        
        resp = self.client.post("/synthesis", params={"speaker": speaker}, json=query, timeout=60.0)
        resp.raise_for_status()
        return resp.content
    
    def batch_synthesize(self, segments: List[Dict]) -> Dict[str, bytes]:
        """Segments: [{segment_id, text, voice?, params?}]"""
        results = {}
        for seg in segments:
            audio = self.synthesize(
                seg["text"],
                seg.get("voice", "speaker_8"),
                **seg.get("params", {})
            )
            results[seg["segment_id"]] = audio
        return results
    
    def get_speakers(self) -> List[Dict]:
        resp = self.client.get("/speakers", timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    
    def health_check(self) -> bool:
        try:
            resp = self.client.get("/version", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False


class EdgeTTSClient(BaseAudioClient):
    """Microsoft Edge TTS client (free, local)."""
    
    JP_VOICES = {
        "female_gentle": "ja-JP-NanamiNeural",    # Best for counselor tone
        "female_calm": "ja-JP-AoiNeural",
        "male_calm": "ja-JP-KeitaNeural",
    }
    
    def __init__(self):
        logger.info("EdgeTTSClient initialized")
    
    def synthesize(self, text: str, voice: str = "female_gentle", rate: str = "+0%", pitch: str = "+0Hz", **params) -> bytes:
        voice_id = self.JP_VOICES.get(voice, voice)
        return asyncio.run(self._synthesize_async(text, voice_id, rate, pitch))
    
    async def _synthesize_async(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data
    
    def batch_synthesize(self, segments: List[Dict]) -> Dict[str, bytes]:
        results = {}
        for seg in segments:
            audio = self.synthesize(
                seg["text"],
                seg.get("voice", "female_gentle"),
                seg.get("rate", "+0%"),
                seg.get("pitch", "+0Hz")
            )
            results[seg["segment_id"]] = audio
        return results


class GoogleCloudTTSClient(BaseAudioClient):
    """Google Cloud Text-to-Speech client (1M chars free/month)."""
    
    def __init__(self, credentials_path: Optional[str] = None):
        from google.cloud import texttospeech
        if credentials_path:
            import os
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
        self._client = texttospeech.TextToSpeechClient()
        logger.info("GoogleCloudTTSClient initialized")
    
    def synthesize(self, text: str, voice: str = "ja-JP-Neural2-B", speaking_rate: float = 1.0, pitch: float = 0.0, **params) -> bytes:
        from google.cloud import texttospeech
        
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        voice_params = texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            name=voice,
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speaking_rate,
            pitch=pitch,
        )
        
        response = self._client.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config,
        )
        return response.audio_content
    
    def batch_synthesize(self, segments: List[Dict]) -> Dict[str, bytes]:
        results = {}
        for seg in segments:
            audio = self.synthesize(
                seg["text"],
                seg.get("voice", "ja-JP-Neural2-B"),
                seg.get("speaking_rate", 1.0),
                seg.get("pitch", 0.0)
            )
            results[seg["segment_id"]] = audio
        return results