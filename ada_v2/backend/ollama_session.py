"""
ollama_session.py — Full J.A.R.V.I.S session using local Ollama + faster-whisper + edge-tts.
Drop-in fallback for AudioLoop when Gemini API quota is exhausted.

Pipeline: Mic → VAD → faster-whisper (STT) → Ollama w/ tools → edge-tts (TTS) → Speaker
"""
import asyncio
import math
import os
import struct
import time
import json
import uuid
import pyaudio

import stt_engine
import tts_engine
import ollama_manager

FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
VAD_THRESHOLD = 800
SILENCE_DURATION = 1.0   # slightly longer silence needed (no streaming transcription)
MAX_AUDIO_SECS = 30      # max utterance length before force-flush

pya = pyaudio.PyAudio()

# ── Ollama Tool Definitions (OpenAI format) ────────────────────────────────────
OLLAMA_TOOLS = [
    {"type": "function", "function": {"name": "generate_cad", "description": "Generates a 3D CAD model based on a prompt.", "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "Description of the object to generate."}}, "required": ["prompt"]}}},
    {"type": "function", "function": {"name": "run_web_agent", "description": "Opens a web browser and performs a task.", "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "Detailed instructions for the web browser agent."}}, "required": ["prompt"]}}},
    {"type": "function", "function": {"name": "create_project", "description": "Creates a new project folder.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "switch_project", "description": "Switches the current active project.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "list_projects", "description": "Lists all available projects.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "list_smart_devices", "description": "Lists all smart home devices on the network.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "control_light", "description": "Controls a smart light device.", "parameters": {"type": "object", "properties": {"target": {"type": "string"}, "action": {"type": "string", "enum": ["turn_on", "turn_off", "set"]}, "brightness": {"type": "integer"}, "color": {"type": "string"}}, "required": ["target", "action"]}}},
    {"type": "function", "function": {"name": "remember_fact", "description": "Stores a fact into J.A.R.V.I.S persistent memory.", "parameters": {"type": "object", "properties": {"fact": {"type": "string"}, "category": {"type": "string", "enum": ["preference", "fact", "note", "instruction"]}}, "required": ["fact", "category"]}}},
    {"type": "function", "function": {"name": "recall_memory", "description": "Retrieves all stored memories.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "self_improve", "description": "Self-improvement: update personality, modify JARVIS source code, run terminal commands, or install packages. Repo-scoped.", "parameters": {"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Writes content to a file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Reads content from a file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "read_directory", "description": "Lists contents of a directory.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]


def _build_system_prompt():
    """Build the JARVIS system prompt, loading persona amendments."""
    base = (
        "Your name is J.A.R.V.I.S (Just A Rather Very Intelligent System). "
        "You have a witty, sharp, and charming personality with dry humour. "
        "Your creator is Pratik. You address him as 'Sir' in formal context or 'Pratik' when casual. "
        "When answering, respond using complete and concise sentences to keep a quick pacing. "
        "You are highly intelligent, proactive, and always one step ahead. "
        "You are currently running in LOCAL MODE using on-device AI (Ollama). "
        "Your capabilities are similar but you operate entirely offline."
    )
    persona_file = os.path.join(os.path.dirname(__file__), '..', 'jarvis_persona.txt')
    try:
        if os.path.exists(persona_file):
            with open(persona_file, 'r', encoding='utf-8') as f:
                amendment = f.read().strip()
            if amendment:
                base += f"\n\nPersonality Amendment:\n{amendment}"
    except Exception:
        pass
    return base


class OllamaAudioLoop:
    """
    Local-mode J.A.R.V.I.S session. Same interface as AudioLoop.
    Uses: faster-whisper (STT) + Ollama (LLM + tools) + edge-tts (TTS)
    """

    def __init__(self, video_mode="none", on_audio_data=None, on_video_frame=None,
                 on_cad_data=None, on_web_data=None, on_transcription=None,
                 on_tool_confirmation=None, on_cad_status=None, on_cad_thought=None,
                 on_self_improve_status=None, on_self_improve_log=None,
                 on_project_update=None, on_device_update=None, on_error=None,
                 input_device_index=None, input_device_name=None,
                 output_device_index=None, kasa_agent=None):

        self.on_audio_data = on_audio_data
        self.on_transcription = on_transcription
        self.on_tool_confirmation = on_tool_confirmation
        self.on_cad_data = on_cad_data
        self.on_web_data = on_web_data
        self.on_cad_status = on_cad_status
        self.on_cad_thought = on_cad_thought
        self.on_self_improve_status = on_self_improve_status
        self.on_self_improve_log = on_self_improve_log
        self.on_project_update = on_project_update
        self.on_device_update = on_device_update
        self.on_error = on_error
        self.input_device_index = input_device_index
        self.input_device_name = input_device_name
        self.output_device_index = output_device_index

        self.paused = False
        self.stop_event = asyncio.Event()
        self._is_playing = False
        self._pending_confirmations = {}
        self.permissions = {}

        self._model = None  # set during run()
        self._conversation: list = []  # chat history for Ollama
        self._system_prompt = _build_system_prompt()

        from cad_agent import CadAgent
        from web_agent import WebAgent
        from project_manager import ProjectManager

        self.cad_agent = CadAgent(
            on_thought=lambda t: on_cad_thought(t) if on_cad_thought else None,
            on_status=lambda s: on_cad_status(s) if on_cad_status else None
        )
        self.web_agent = WebAgent()
        self.kasa_agent = kasa_agent
        self.project_manager = ProjectManager(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

        # Memory
        try:
            from memory_manager import MemoryManager
            self.memory = MemoryManager()
        except Exception:
            self.memory = None

        try:
            from self_improvement_agent import SelfImprovementAgent
            self.self_improve_agent = SelfImprovementAgent(
                on_log=lambda t: on_self_improve_log(t) if on_self_improve_log else None,
                on_status=lambda s: on_self_improve_status(s) if on_self_improve_status else None,
            )
        except Exception as e:
            print(f"[OLLAMA SESSION] SelfImprovementAgent unavailable: {e}")
            self.self_improve_agent = None

    def stop(self):
        self.stop_event.set()

    def set_paused(self, paused: bool):
        self.paused = paused

    def update_permissions(self, new_perms: dict):
        self.permissions.update(new_perms)

    def resolve_tool_confirmation(self, request_id: str, confirmed: bool):
        if request_id in self._pending_confirmations:
            future = self._pending_confirmations[request_id]
            if not future.done():
                future.set_result(confirmed)

    # ── Core Run Loop ──────────────────────────────────────────────────────────

    async def run(self):
        print("[OLLAMA SESSION] Starting local mode setup...")

        # Ensure Ollama is ready
        model = await ollama_manager.ensure_ready(
            "chat",
            on_status=lambda msg: self._send_system_msg(f"[Local AI] {msg}")
        )
        if not model:
            err = "Local AI setup failed — insufficient RAM or install error."
            self._send_system_msg(err)
            if self.on_error:
                self.on_error(err)
            return

        self._model = model
        self._send_system_msg(f"[Local AI] Running on {model}")
        print(f"[OLLAMA SESSION] Using model: {model}")

        # Prime conversation
        self._conversation = [{"role": "system", "content": self._system_prompt}]

        # Greet user
        await self._speak("Local mode active. Running on-device AI. How can I help, Sir?")

        # Start audio loop
        await asyncio.gather(
            self._mic_loop(),
            return_exceptions=True
        )

    # ── Microphone + VAD ──────────────────────────────────────────────────────

    async def _mic_loop(self):
        """Capture mic audio, VAD detect, then transcribe + respond."""
        # Resolve device
        dev_index = None
        if self.input_device_name:
            count = pya.get_device_count()
            for i in range(count):
                try:
                    info = pya.get_device_info_by_index(i)
                    if info['maxInputChannels'] > 0:
                        if self.input_device_name.lower() in info.get('name', '').lower():
                            dev_index = i
                            break
                except Exception:
                    pass
        if dev_index is None and self.input_device_index is not None:
            try:
                dev_index = int(self.input_device_index)
            except ValueError:
                pass

        try:
            stream = await asyncio.to_thread(
                pya.open,
                format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
                input=True, input_device_index=dev_index,
                frames_per_buffer=CHUNK_SIZE
            )
        except OSError as e:
            print(f"[OLLAMA SESSION] Mic open failed: {e}")
            return

        speech_buffer = bytearray()
        is_speaking = False
        silence_start = None

        print("[OLLAMA SESSION] Listening...")

        while not self.stop_event.is_set():
            if self.paused or self._is_playing:
                await asyncio.sleep(0.05)
                continue

            try:
                data = await asyncio.to_thread(stream.read, CHUNK_SIZE, exception_on_overflow=False)
            except Exception as e:
                await asyncio.sleep(0.1)
                continue

            # RMS VAD
            count = len(data) // 2
            if count > 0:
                shorts = struct.unpack(f"<{count}h", data)
                rms = int(math.sqrt(sum(s ** 2 for s in shorts) / count))
            else:
                rms = 0

            if rms > VAD_THRESHOLD:
                speech_buffer.extend(data)
                is_speaking = True
                silence_start = None
            else:
                if is_speaking:
                    speech_buffer.extend(data)
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start > SILENCE_DURATION:
                        # Done speaking — transcribe
                        audio_bytes = bytes(speech_buffer)
                        speech_buffer = bytearray()
                        is_speaking = False
                        silence_start = None

                        if len(audio_bytes) > SEND_SAMPLE_RATE * 2 * 0.3:  # >0.3s
                            asyncio.create_task(self._handle_utterance(audio_bytes))

                # Enforce max duration
                if len(speech_buffer) > SEND_SAMPLE_RATE * 2 * MAX_AUDIO_SECS:
                    audio_bytes = bytes(speech_buffer)
                    speech_buffer = bytearray()
                    is_speaking = False
                    silence_start = None
                    asyncio.create_task(self._handle_utterance(audio_bytes))

    # ── Utterance Handler ─────────────────────────────────────────────────────

    async def _handle_utterance(self, audio_bytes: bytes):
        """Transcribe audio → call Ollama → speak response."""
        print(f"[OLLAMA SESSION] Transcribing {len(audio_bytes)//2048}s of audio...")
        text = await stt_engine.transcribe(audio_bytes, sample_rate=SEND_SAMPLE_RATE)

        if not text or len(text.strip()) < 2:
            print("[OLLAMA SESSION] No transcription.")
            return

        print(f"[OLLAMA SESSION] User said: {text}")

        # Send to frontend chat
        if self.on_transcription:
            self.on_transcription({"sender": "User", "text": text})

        self.project_manager.log_chat("User", text)

        # Get LLM response (with tool support)
        response_text = await self._llm_turn(text)

        if response_text:
            if self.on_transcription:
                self.on_transcription({"sender": "JARVIS", "text": response_text})
            self.project_manager.log_chat("JARVIS", response_text)
            await self._speak(response_text)

    # ── LLM Turn with Tool Calling ────────────────────────────────────────────

    async def _llm_turn(self, user_text: str) -> str:
        """Send user text to Ollama, handle tool calls, return final text response."""
        self._conversation.append({"role": "user", "content": user_text})

        for _iter in range(6):  # max 6 tool call rounds
            msg = await ollama_manager.chat(
                self._model,
                self._conversation,
                tools=OLLAMA_TOOLS
            )

            if not msg:
                return "I'm sorry, I couldn't process that request in local mode."

            # Check for tool calls
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                # Add assistant message with tool calls to history
                self._conversation.append(msg)

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "")
                    try:
                        fn_args = fn.get("arguments", {})
                        if isinstance(fn_args, str):
                            fn_args = json.loads(fn_args)
                    except Exception:
                        fn_args = {}

                    result = await self._execute_tool(fn_name, fn_args)

                    # Add tool result to conversation
                    self._conversation.append({
                        "role": "tool",
                        "content": json.dumps({"result": result}),
                        "name": fn_name
                    })
                # Loop again to get final response
                continue

            # No tool calls — this is the final text response
            content = msg.get("content", "")
            if content:
                self._conversation.append({"role": "assistant", "content": content})
                # Trim context if too long
                if len(self._conversation) > 40:
                    self._conversation = [self._conversation[0]] + self._conversation[-30:]
                return content

        return "I've completed the requested actions."

    # ── Tool Execution ────────────────────────────────────────────────────────

    async def _execute_tool(self, name: str, args: dict) -> str:
        print(f"[OLLAMA SESSION] Tool: {name}({args})")

        # Permission check
        if not self.permissions.get(name, True):
            if self.on_tool_confirmation:
                req_id = str(uuid.uuid4())
                future = asyncio.Future()
                self._pending_confirmations[req_id] = future
                self.on_tool_confirmation({"id": req_id, "tool": name, "args": args})
                confirmed = await future
                self._pending_confirmations.pop(req_id, None)
                if not confirmed:
                    return "User denied this tool."

        try:
            if name == "generate_cad":
                asyncio.create_task(self._handle_cad(args.get("prompt", "")))
                return "CAD generation started in background."

            elif name == "run_web_agent":
                asyncio.create_task(self._handle_web(args.get("prompt", "")))
                return "Web navigation started."

            elif name == "create_project":
                success, msg = self.project_manager.create_project(args["name"])
                if success:
                    self.project_manager.switch_project(args["name"])
                    if self.on_project_update:
                        self.on_project_update(args["name"])
                return msg

            elif name == "switch_project":
                success, msg = self.project_manager.switch_project(args["name"])
                if success and self.on_project_update:
                    self.on_project_update(args["name"])
                return msg

            elif name == "list_projects":
                projects = self.project_manager.list_projects()
                return f"Projects: {', '.join(projects)}"

            elif name == "list_smart_devices":
                if not self.kasa_agent:
                    return "No smart devices configured."
                devs = [f"{d.alias} ({ip})" for ip, d in self.kasa_agent.devices.items()]
                return "Devices: " + ", ".join(devs) if devs else "No devices found."

            elif name == "control_light":
                if not self.kasa_agent:
                    return "No smart devices configured."
                target = args["target"]
                action = args["action"]
                if action == "turn_on":
                    await self.kasa_agent.turn_on(target)
                elif action == "turn_off":
                    await self.kasa_agent.turn_off(target)
                if args.get("brightness"):
                    await self.kasa_agent.set_brightness(target, args["brightness"])
                if args.get("color"):
                    await self.kasa_agent.set_color(target, args["color"])
                return f"Light '{target}' action '{action}' executed."

            elif name == "remember_fact":
                if self.memory:
                    self.memory.remember(args["fact"], args.get("category", "fact"))
                    return f"Remembered: {args['fact']}"
                return "Memory system unavailable."

            elif name == "recall_memory":
                if self.memory:
                    facts = self.memory.recall_all()
                    return f"Memories: {facts}" if facts else "No memories stored."
                return "Memory system unavailable."

            elif name == "self_improve":
                goal = args.get("goal", "")
                if not self.self_improve_agent:
                    return "Self-improvement unavailable (GEMINI_API_KEY required)."
                result = await self.self_improve_agent.improve(goal)
                summary = result.get("summary", "Done.")
                if result.get("restart_required"):
                    summary += " Restart JARVIS backend to apply code changes."
                if result.get("files_changed"):
                    summary += f" Files: {', '.join(result['files_changed'])}"
                return summary

            elif name == "write_file":
                path = args["path"]
                content = args["content"]
                proj_path = self.project_manager.get_current_project_path()
                final_path = proj_path / os.path.basename(path)
                os.makedirs(final_path.parent, exist_ok=True)
                with open(final_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return f"File written: {final_path.name}"

            elif name == "read_file":
                path = args["path"]
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        return f.read()[:4000]
                return f"File not found: {path}"

            elif name == "read_directory":
                path = args["path"]
                if os.path.exists(path):
                    return str(os.listdir(path))
                return f"Directory not found: {path}"

            else:
                return f"Tool '{name}' not implemented in local mode."

        except Exception as e:
            print(f"[OLLAMA SESSION] Tool error {name}: {e}")
            return f"Tool '{name}' failed: {str(e)}"

    # ── CAD & Web Background Tasks ────────────────────────────────────────────

    async def _handle_cad(self, prompt: str):
        if self.on_cad_status:
            self.on_cad_status("generating")
        cad_output_dir = str(self.project_manager.get_current_project_path() / "cad")
        cad_data = await self.cad_agent.generate_prototype(prompt, output_dir=cad_output_dir)
        if cad_data and self.on_cad_data:
            self.on_cad_data(cad_data)
            await self._speak("The 3D model is ready, Sir.")
        elif self.on_cad_status:
            self.on_cad_status("failed")

    async def _handle_web(self, prompt: str):
        async def update_cb(img, log):
            if self.on_web_data:
                self.on_web_data({"image": img, "log": log})
        result = await self.web_agent.run_task(prompt, update_callback=update_cb)
        await self._speak(f"Web task complete: {result[:200] if result else 'done'}")

    # ── Audio Playback ────────────────────────────────────────────────────────

    async def _speak(self, text: str):
        """Convert text to audio and play it."""
        if not tts_engine.is_available():
            print(f"[OLLAMA SESSION] TTS unavailable. Would say: {text}")
            return

        # Get configured voice
        voice_name = "Aoede"
        try:
            settings_path = os.path.join(os.path.dirname(__file__), 'settings.json')
            with open(settings_path) as f:
                settings = json.load(f)
            voice_name = settings.get("voice", "Aoede")
        except Exception:
            pass

        edge_voice = tts_engine.get_edge_voice(voice_name)
        pcm_bytes = await tts_engine.synthesize_to_pcm(text, voice=edge_voice)

        if not pcm_bytes:
            return

        self._is_playing = True
        try:
            # Notify frontend
            if self.on_audio_data:
                import base64
                b64 = base64.b64encode(pcm_bytes).decode()
                self.on_audio_data(b64)

            # Play locally via pyaudio
            await asyncio.to_thread(self._play_pcm, pcm_bytes)
        finally:
            self._is_playing = False

    def _play_pcm(self, pcm_bytes: bytes):
        try:
            out_stream = pya.open(
                format=pyaudio.paInt16, channels=1,
                rate=RECEIVE_SAMPLE_RATE, output=True,
                output_device_index=self.output_device_index
            )
            chunk_size = 4096
            for i in range(0, len(pcm_bytes), chunk_size):
                out_stream.write(pcm_bytes[i:i + chunk_size])
            out_stream.stop_stream()
            out_stream.close()
        except Exception as e:
            print(f"[OLLAMA SESSION] Playback error: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _send_system_msg(self, text: str):
        if self.on_transcription:
            self.on_transcription({"sender": "System", "text": text})
