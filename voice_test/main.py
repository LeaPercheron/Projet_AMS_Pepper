#!/usr/bin/env python3
# Mini projet test vocal Pepper (sans scan vision)

from __future__ import annotations

import argparse
import asyncio
import os
import re
import signal
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


ROOT = Path(__file__).resolve().parents[1]
if load_dotenv is not None:
    load_dotenv(ROOT / ".env")
    load_dotenv()

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tablet"))

from assistant.adapters.pepper_adapter import PepperAdapter
from assistant.adapters.ssh_bridge_adapter import SSHBridgeAdapter
from assistant.llm import OpenAIHTTPFallbackClient, HTTPVoiceFallback, VoiceFallbackConfig
from server import TabletServer, ServerConfig


class VoiceOnlyLab:
    def __init__(
        self,
        pepper_ip: str,
        ws_host: str,
        ws_port: int,
        tablet_url: str = "",
        use_ssh_bridge: bool = False,
        ssh_user: str = "nao",
        ssh_port: int = 22,
        ssh_python: str = "python",
    ):
        self.pepper_ip = pepper_ip
        self.ws_host = ws_host
        self.ws_port = ws_port
        self.tablet_url = tablet_url.strip()
        self.use_ssh_bridge = bool(use_ssh_bridge)
        self.ssh_user = ssh_user
        self.ssh_port = int(ssh_port)
        self.ssh_python = ssh_python

        self.adapter = None
        self.text_client: Optional[OpenAIHTTPFallbackClient] = None
        self.voice_fallback: Optional[HTTPVoiceFallback] = None
        self.tablet_server: Optional[TabletServer] = None

        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._voice_request_seq = 0
        self._voice_transcript_seq = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def setup(self):
        self._loop = asyncio.get_running_loop()

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY manquante.")

        if self.use_ssh_bridge:
            self.adapter = SSHBridgeAdapter(
                ip=self.pepper_ip,
                port=9559,
                ssh_user=self.ssh_user,
                ssh_port=self.ssh_port,
                ssh_python=self.ssh_python,
            )
        else:
            self.adapter = PepperAdapter(ip=self.pepper_ip, port=9559)
        if not self.adapter.connect():
            raise RuntimeError("Connexion Pepper impossible.")

        fallback_model = (os.getenv("OPENAI_HTTP_FALLBACK_MODEL", "") or "gpt-4o-mini").strip()
        self.text_client = OpenAIHTTPFallbackClient(api_key=api_key, model=fallback_model)

        input_sr = int(getattr(getattr(self.adapter, "config", None), "sample_rate", 48000) or 48000)
        input_ch = int(getattr(getattr(self.adapter, "config", None), "channels_in", 4) or 4)
        mono_channel_index = int(os.getenv("OPENAI_HTTP_MONO_CHANNEL_INDEX", "2") or "2")

        # PepperAdapter tombe souvent sur le fallback recorder (WAV pull).
        # En mode front-only, le flux réel est mono 16 kHz.
        front_only = os.getenv("PEPPER_AUDIO_RECORDER_FRONT_ONLY", "1").strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(self.adapter, PepperAdapter) and front_only:
            input_sr = 16000
            input_ch = 1
            mono_channel_index = 0

        self.voice_fallback = HTTPVoiceFallback(
            api_key=api_key,
            text_client=self.text_client,
            speak_callback=self._speak_blocking,
            context_provider=lambda: {},
            on_transcript=self._on_transcript,
            on_answer=self._on_answer,
            config=VoiceFallbackConfig(
                input_sample_rate=input_sr,
                input_channels=input_ch,
                transcription_model=(os.getenv("OPENAI_HTTP_TRANSCRIPTION_MODEL", "") or "whisper-1").strip(),
                speech_threshold=float(os.getenv("OPENAI_HTTP_SPEECH_THRESHOLD", "0.010") or "0.010"),
                min_utterance_s=float(os.getenv("OPENAI_HTTP_MIN_UTTERANCE_S", "0.35") or "0.35"),
                end_silence_s=float(os.getenv("OPENAI_HTTP_END_SILENCE_S", "0.90") or "0.90"),
                mono_channel_index=mono_channel_index,
                input_gain=float(os.getenv("OPENAI_HTTP_INPUT_GAIN", "1.0") or "1.0"),
                manual_trigger=True,
                listen_window_s=9.0,
                local_stt_enabled=os.getenv("OPENAI_HTTP_LOCAL_STT_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"},
                local_stt_model=(os.getenv("OPENAI_HTTP_LOCAL_STT_MODEL", "") or "mlx-community/distil-whisper-large-v3").strip(),
                local_stt_path=os.getenv("OPENAI_HTTP_LOCAL_STT_PATH", "").strip(),
                offline_answer_on_error=True,
            ),
        )
        self.voice_fallback.start()

        if not self.adapter.start_audio_capture(self.voice_fallback.ingest):
            raise RuntimeError("Capture audio Pepper indisponible.")

        self.tablet_server = TabletServer(ServerConfig(host=self.ws_host, port=self.ws_port))
        self.tablet_server.register_handler("start_voice_question", self._handle_start_voice_question)
        self.tablet_server.register_handler("ask_question", self._handle_text_disabled)
        print(f"[voice_test] WS prêt: ws://{self.ws_host}:{self.ws_port}")

    async def run(self):
        if not self.tablet_server:
            raise RuntimeError("Serveur tablette non initialisé.")

        self._tasks.append(asyncio.create_task(self.tablet_server.start(), name="voice_tablet_ws"))
        await asyncio.sleep(0.2)
        await self._auto_show_tablet()
        print("[voice_test] Démarré. Ctrl+C pour arrêter.")
        await self._shutdown_event.wait()

    async def shutdown(self):
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
        self._tasks.clear()

        if self.tablet_server:
            try:
                await self.tablet_server.stop()
            except Exception:
                pass
            self.tablet_server = None
        self._loop = None

        if self.voice_fallback:
            self.voice_fallback.stop()
            self.voice_fallback = None

        if self.adapter:
            try:
                self.adapter.disconnect()
            except Exception:
                pass
            self.adapter = None

        print("[voice_test] Arrêt propre.")

    def request_shutdown(self):
        self._shutdown_event.set()

    async def _auto_show_tablet(self):
        if not self.adapter or not self.tablet_url:
            return
        base_url = self.tablet_url.strip()
        await self._check_tablet_http(base_url)

        candidates = [base_url]
        encoded_url = self._encode_ws_query_param(base_url)
        if encoded_url != base_url:
            candidates.append(encoded_url)

        for candidate in candidates:
            for attempt in range(1, 4):
                target = self._with_cache_buster(candidate)
                try:
                    ok = await asyncio.to_thread(self.adapter.show_on_tablet, target)
                    if ok:
                        print(f"[voice_test] Tablette affichée (tentative {attempt}): {target}")
                        return
                except Exception as e:
                    print(f"[voice_test] Erreur affichage tablette (tentative {attempt}): {e}")
                await asyncio.sleep(1.0)

        print("[voice_test] Échec affichage tablette après retries.")
        print(f"[voice_test] URL testée: {base_url}")
        if encoded_url != base_url:
            print(f"[voice_test] URL encodée testée: {encoded_url}")

    async def _check_tablet_http(self, url: str):
        try:
            await asyncio.to_thread(urllib.request.urlopen, url, None, 1.5)
            print(f"[voice_test] HTTP tablette joignable: {url}")
        except Exception:
            print("[voice_test] HTTP tablette non joignable localement.")
            print(
                "[voice_test] Lance d'abord: "
                "cd voice_test/tablet && python3 -m http.server 8081 --bind 0.0.0.0"
            )

    @staticmethod
    def _encode_ws_query_param(url: str) -> str:
        def _replace(match: re.Match) -> str:
            raw_value = match.group(2)
            decoded = unquote(raw_value)
            encoded = quote(decoded, safe="")
            return match.group(1) + encoded

        return re.sub(r"([?&]ws=)([^&]+)", _replace, url, count=1)

    @staticmethod
    def _with_cache_buster(url: str) -> str:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}cb={int(time.time())}"

    def _speak_blocking(self, answer_text: str):
        if self.adapter and answer_text:
            self.adapter.say(answer_text, True)

    def _on_transcript(self, transcript: str):
        if not transcript:
            return
        self._voice_transcript_seq += 1
        print(f"[voice_test] Transcription: {transcript}")
        if not self.tablet_server:
            return
        if not self._loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.tablet_server.send_security_alert(True, "Question entendue", transcript),
                self._loop,
            )
        except Exception:
            pass

    def _on_answer(self, transcript: str, answer: str):
        if answer:
            print(f"[voice_test] Réponse: {answer}")
        if not self.tablet_server:
            return
        if not self._loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.tablet_server.send_qa_answer(True, transcript, answer),
                self._loop,
            )
        except Exception:
            pass

    async def _handle_text_disabled(self, websocket, data):
        if self.tablet_server:
            await self.tablet_server._send_error(
                websocket,
                "Mode test vocal: question texte désactivée.",
            )

    async def _handle_start_voice_question(self, websocket, data):
        if not self.voice_fallback:
            await self.tablet_server._send_error(websocket, "Fallback vocal indisponible.")
            return

        duration = 9.0
        try:
            duration = max(3.0, min(20.0, float((data or {}).get("duration_s", 9.0))))
        except Exception:
            pass

        vf_config = getattr(self.voice_fallback, "config", None)
        if self.adapter and vf_config:
            detected_channels = int(getattr(self.adapter, "_audio_pull_detected_channels", 0) or 0)
            detected_rate = int(getattr(self.adapter, "_audio_pull_detected_rate", 0) or 0)
            if detected_channels > 0:
                vf_config.input_channels = detected_channels
            if detected_rate > 0:
                vf_config.input_sample_rate = detected_rate

        await asyncio.to_thread(self.voice_fallback.arm_listen_window, duration)
        chunk_count = 0
        if self.adapter:
            chunk_count = int(getattr(self.adapter, "_audio_pull_chunk_count", 0) or 0)
        print(f"[voice_test] Fenêtre d'écoute ouverte ({duration:.1f}s) - chunks audio vus: {chunk_count}")
        if self.adapter:
            await asyncio.to_thread(self.adapter.say, "Je vous écoute.", False)

        self._voice_request_seq += 1
        request_id = self._voice_request_seq
        transcript_seq_before = self._voice_transcript_seq

        await self.tablet_server.send_security_alert(
            websocket,
            "Question vocale",
            f"Parlez maintenant. Fenêtre d'écoute active pendant {int(duration)} secondes.",
        )
        asyncio.create_task(
            self._notify_voice_timeout_if_silent(
                websocket=websocket,
                request_id=request_id,
                duration_s=duration,
                transcript_seq_before=transcript_seq_before,
            )
        )

    async def _notify_voice_timeout_if_silent(
        self,
        websocket,
        request_id: int,
        duration_s: float,
        transcript_seq_before: int,
    ):
        await asyncio.sleep(max(1.0, duration_s) + 2.5)
        if request_id != self._voice_request_seq:
            return
        if self._voice_transcript_seq > transcript_seq_before:
            return
        if not self.tablet_server:
            return
        try:
            no_audio_chunk = False
            if self.adapter and self.adapter.__class__.__name__ == "PepperAdapter":
                no_audio_chunk = int(getattr(self.adapter, "_audio_pull_chunk_count", 0) or 0) == 0

            timeout_msg = "Je n'ai pas bien entendu. Rapprochez-vous et réessayez."
            if no_audio_chunk:
                timeout_msg = (
                    "Aucun flux micro reçu depuis Pepper. "
                    "Essayez le mode --ssh-bridge pour valider la chaîne vocale."
                )
            await self.tablet_server.send_security_alert(
                websocket,
                "Question vocale",
                timeout_msg,
            )
            if self.adapter:
                await asyncio.to_thread(
                    self.adapter.say,
                    "Je n'ai pas bien entendu. Pouvez-vous répéter ?" if not no_audio_chunk else "Le micro Pepper ne remonte pas encore de son.",
                    False,
                )
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mini projet test vocal Pepper (sans scan)")
    parser.add_argument("--pepper-ip", required=True, help="IP Pepper")
    parser.add_argument("--ws-host", default="0.0.0.0", help="Host WebSocket")
    parser.add_argument("--ws-port", type=int, default=8870, help="Port WebSocket")
    parser.add_argument(
        "--tablet-url",
        default="",
        help="URL à afficher sur tablette Pepper (ex: http://IP_MAC:8081/index.html?ws=ws://IP_MAC:8870)",
    )
    parser.add_argument("--ssh-bridge", action="store_true", help="Utiliser SSHBridgeAdapter au lieu de PepperAdapter.")
    parser.add_argument("--ssh-user", default="nao", help="Utilisateur SSH robot.")
    parser.add_argument("--ssh-port", type=int, default=22, help="Port SSH robot.")
    parser.add_argument("--ssh-python", default="python", help="Binaire Python distant (SSH bridge).")
    return parser.parse_args()


async def amain():
    args = parse_args()
    app = VoiceOnlyLab(
        pepper_ip=args.pepper_ip,
        ws_host=args.ws_host,
        ws_port=args.ws_port,
        tablet_url=args.tablet_url,
        use_ssh_bridge=args.ssh_bridge,
        ssh_user=args.ssh_user,
        ssh_port=args.ssh_port,
        ssh_python=args.ssh_python,
    )

    def _signal_handler(sig, frame):
        app.request_shutdown()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    await app.setup()
    try:
        await app.run()
    finally:
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(amain())
