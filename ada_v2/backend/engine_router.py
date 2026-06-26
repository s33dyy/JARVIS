"""
engine_router.py - AI Engine Router for ADA/JARVIS

Single source of truth for ALL LLM calls.
Every agent (ada.py, cad_agent.py, web_agent.py) must use this
instead of calling Gemini directly.

Priority chain (respects settings.json):
  1. LOCAL: MLX server on :8080 (if running)
  2. LOCAL: Ollama on :11434 (auto-install)
  3. CLOUD: Gemini 2.0 Flash (if key present)
  4. CLOUD: OpenRouter cheapest (if key present)

If preferred_engine='gemini': skip 1 & 2.
If preferred_engine='local': skip 3 & 4.
If preferred_engine='auto': try in order above.
"""

import asyncio
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Callable, Dict, Any, AsyncGenerator
from datetime import datetime

import aiohttp
import psutil

# Try to import google-generativeai for Gemini
GOOGLE_AVAILABLE = True
try:
    from google import genai
    from google.genai import types
except ImportError:
    GOOGLE_AVAILABLE = False

# Try to import ollama_manager
OLLAMA_AVAILABLE = True
try:
    from backend import ollama_manager
except ImportError:
    OLLAMA_AVAILABLE = False

class EngineStatus:
    """Engine availability status."""
    
    def __init__(self):
        self.mlx: Dict[str, Any] = {'available': False, 'model': None}
        self.ollama: Dict[str, Any] = {'available': False, 'models': []}
        self.gemini: Dict[str, Any] = {'available': False}
        self.openrouter: Dict[str, Any] = {'available': False}


class EngineRouter:
    """
    Single source of truth for ALL LLM calls.
    Every agent must use this instead of calling Gemini directly.
    """

    def __init__(self, settings: dict, emit_fn=None):
        self.settings = settings
        self.emit = emit_fn
        self._active_engine = None
        self._engine_status = EngineStatus()
        self._gemini_client = None
        self._ollama_client = None

    async def probe_engines(self) -> EngineStatus:
        """
        Check what's available RIGHT NOW.
        Returns status dict.
        Run on startup + emit to frontend.
        """
        status = EngineStatus()

        # Check MLX
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2.0)) as session:
                async with session.get('http://localhost:8080/health', timeout=2.0) as resp:
                    status.mlx['available'] = resp.status == 200
                    if resp.status == 200:
                        async with session.get('http://localhost:8080/models') as r:
                            data = await r.json()
                            status.mlx['model'] = data.get('model', None)
        except Exception:
            status.mlx['available'] = False

        # Check Ollama
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2.0)) as session:
                async with session.get('http://localhost:11434/api/tags', timeout=2.0) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        status.ollama['available'] = True
                        status.ollama['models'] = [m['name'] for m in data.get('models', [])]
        except Exception:
            status.ollama['available'] = False

        # Check Gemini key
        gemini_key = self.settings.get('gemini_api_key')
        status.gemini['available'] = bool(gemini_key and len(gemini_key) > 20)

        # Check OpenRouter key
        openrouter_key = self.settings.get('openrouter_api_key')
        status.openrouter['available'] = bool(openrouter_key and len(openrouter_key) > 20)

        self._engine_status = status
        if self.emit:
            self.emit('engine_status', status.__dict__)
        return status

    async def complete(
        self,
        prompt: str,
        system: str = '',
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        on_token: Optional[Callable[[str], None]] = None,
        task_type: str = 'general'
    ) -> str:
        """
        Main entry point for all LLM calls.
        Tries engines in priority order.
        On failure: logs reason, tries next.
        If ALL fail: returns structured error +
        emits 'engine_all_failed' to frontend.
        """

        preferred = self.settings.get('preferred_engine', 'auto')
        errors = []

        chain = self._build_chain(preferred, task_type)

        for engine_name, engine_fn in chain:
            try:
                if self.emit:
                    self.emit('engine_active', {'engine': engine_name})
                result = await engine_fn(
                    prompt, system, temperature,
                    max_tokens, stream, on_token
                )
                self._active_engine = engine_name
                return result
            except Exception as e:
                err = f'{engine_name}: {str(e)[:100]}'
                errors.append(err)
                if self.emit:
                    self.emit('engine_fallback', {
                        'failed': engine_name,
                        'reason': str(e)[:100],
                        'trying_next': True
                    })
                continue

        # ALL FAILED
        error_msg = ' | '.join(errors)
        if self.emit:
            self.emit('engine_all_failed', {
                'errors': errors,
                'message': 'All AI engines failed. Check API keys in Settings.'
            })
        raise RuntimeError(f'All engines failed: {error_msg}')

    def _build_chain(self, preferred, task_type):
        """Returns ordered list of (name, fn) tuples"""
        s = self._engine_status
        chain = []

        if preferred in ('auto', 'local'):
            if s.mlx.available:
                chain.append(('MLX', self._call_mlx))
            if s.ollama.available:
                chain.append(('Ollama', self._call_ollama))

        if preferred in ('auto', 'gemini', 'cloud'):
            if s.gemini.available and GOOGLE_AVAILABLE:
                chain.append(('Gemini', self._call_gemini))

        if preferred in ('auto', 'cloud'):
            if s.openrouter.available:
                chain.append(('OpenRouter', self._call_openrouter))

        if not chain:
            chain = [('Gemini', self._call_gemini)]
            if self.emit:
                self.emit('engine_warning', {
                    'message': f'Preferred engine "{preferred}" unavailable. '
                               f'Falling back to cloud.'
                })

        return chain

    async def _call_mlx(
        self,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
        on_token: Optional[Callable[[str], None]]
    ) -> str:
        """Call MLX server via OpenAI-compatible API."""
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120)
            ) as session:
                payload = {
                    'model': 'mlx-model',
                    'prompt': prompt,
                    'system': system,
                    'temperature': temperature,
                    'max_tokens': max_tokens,
                    'stream': stream,
                    'stream_options': {'include_usage': True} if stream else None
                }
                async with session.post(
                    'http://localhost:8080/v1/chat/completions',
                    json=payload
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f'MLX API error: {resp.status}')
                    
                    if stream:
                        full_response = ''
                        async for line in resp.content:
                            if line:
                                try:
                                    chunk = json.loads(line.decode('utf-8'))
                                    if 'choices' in chunk and chunk['choices']:
                                        delta = chunk['choices'][0].get('delta', {})
                                        if 'content' in delta:
                                            content = delta['content']
                                            full_response += content
                                            if on_token:
                                                on_token(content)
                                except json.JSONDecodeError:
                                    pass
                        return full_response
                    else:
                        data = await resp.json()
                        return data.get('choices', [{}])[0].get('message', {}).get('content', '')
        except Exception as e:
            raise Exception(f'MLX error: {str(e)}')

    async def _call_ollama(
        self,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
        on_token: Optional[Callable[[str], None]]
    ) -> str:
        """Call Ollama server via /api/generate or /api/chat."""
        if not OLLAMA_AVAILABLE:
            raise Exception('Ollama support not available')

        model = self.settings.get('ollama_model', 'auto')
        if model == 'auto':
            models = self._engine_status.ollama.get('models', [])
            if not models:
                raise Exception('No Ollama models available')
            
            codable_models = [m for m in models if 'coder' in m or 'code' in m]
            if codable_models:
                model = codable_models[0]
            else:
                model = models[0]

        ram_gb = self._get_ram_gb()
        is_code_model = task_type == 'code'

        if is_code_model:
            if ram_gb >= 16 and 'qwen2.5-coder:14b' in model:
                pass
            elif ram_gb >= 8 and 'qwen2.5-coder:7b' in model:
                pass
            elif ram_gb >= 4 and 'qwen2.5-coder:3b' in model:
                pass
            elif ram_gb >= 2 and 'qwen2.5-coder:1.5b' in model:
                pass

        # Determine endpoint
        use_chat = 'coder' in model or 'chat' in model

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=300)
        ) as session:
            if use_chat:
                payload = {
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': system} if system else {'role': 'system', 'content': ''},
                        {'role': 'user', 'content': prompt}
                    ],
                    'stream': stream,
                    'options': {
                        'temperature': temperature,
                        'num_ctx': 8192 if is_code_model else 2048
                    }
                }
                async with session.post(
                    'http://localhost:11434/api/chat',
                    json=payload
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f'Ollama chat API error: {resp.status}')

                    if stream:
                        full_response = ''
                        async for line in resp.content:
                            if line:
                                try:
                                    chunk = json.loads(line.decode('utf-8'))
                                    if 'message' in chunk and 'content' in chunk['message']:
                                        content = chunk['message']['content']
                                        full_response += content
                                        if on_token:
                                            on_token(content)
                                except json.JSONDecodeError:
                                    pass
                        return full_response
                    else:
                        data = await resp.json()
                        return data.get('message', {}).get('content', '')
            else:
                payload = {
                    'model': model,
                    'prompt': prompt,
                    'stream': stream,
                    'options': {
                        'temperature': temperature,
                        'num_ctx': 8192 if is_code_model else 2048
                    }
                }
                if system:
                    payload['system'] = system

                async with session.post(
                    'http://localhost:11434/api/generate',
                    json=payload
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f'Ollama generate API error: {resp.status}')

                    if stream:
                        full_response = ''
                        async for line in resp.content:
                            if line:
                                try:
                                    chunk = json.loads(line.decode('utf-8'))
                                    if 'response' in chunk:
                                        content = chunk['response']
                                        full_response += content
                                        if on_token:
                                            on_token(content)
                                except json.JSONDecodeError:
                                    pass
                        return full_response
                    else:
                        data = await resp.json()
                        return data.get('response', '')

    async def _call_gemini(
        self,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
        on_token: Optional[Callable[[str], None]]
    ) -> str:
        """Call Gemini 2.0 Flash or other Gemini models."""
        if not GOOGLE_AVAILABLE:
            raise Exception('Gemini SDK not available')

        if not self._gemini_client:
            api_key = self.settings.get('gemini_api_key', '')
            if not api_key:
                raise Exception('Gemini API key required')
            self._gemini_client = genai.Client(
                http_options={"api_version": "v1beta"},
                api_key=api_key
            )

        model = self.settings.get('gemini_model', 'gemini-2.0-flash')

        try:
            if stream:
                raw_content = ''
                stream = await self._gemini_client.aio.models.generate_content_stream(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=temperature,
                        thinking_config=types.ThinkingConfig(include_thoughts=True)
                    )
                )

                async for chunk in stream:
                    if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                        for part in chunk.candidates[0].content.parts:
                            if part.text:
                                raw_content += part.text
                                if on_token:
                                    on_token(part.text)
                            elif hasattr(part, 'thought') and part.thought:
                                if on_token:
                                    on_token(f'\n[THOUGHT] {part.thought}')
                return raw_content
            else:
                response = await self._gemini_client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=temperature
                    )
                )
                if response.candidates and response.candidates[0].content:
                    return response.candidates[0].content.parts[0].text
                return ''
        except Exception as e:
            raise Exception(f'Gemini error: {str(e)}')

    async def _call_openrouter(
        self,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
        on_token: Optional[Callable[[str], None]]
    ) -> str:
        """Call OpenRouter API."""
        api_key = self.settings.get('openrouter_api_key', '')
        if not api_key:
            raise Exception('OpenRouter API key required')

        model = self.settings.get('openrouter_model', 'mistralai/mistral-7b-instruct:free')

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=180)
        ) as session:
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }

            payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system} if system else {'role': 'system', 'content': ''},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': temperature,
                'max_tokens': max_tokens,
                'stream': stream
            }

            async with session.post(
                'https://openrouter.ai/api/v1/chat/completions',
                json=payload,
                headers=headers
            ) as resp:
                if resp.status != 200:
                    error_data = await resp.text()
                    raise Exception(f'OpenRouter API error: {resp.status} - {error_data}')

                if stream:
                    full_response = ''
                    async for line in resp.content:
                        if line:
                            line_text = line.decode('utf-8')
                            if line_text.startswith('data: '):
                                data_str = line_text[6:]
                                if data_str == '[DONE]':
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                    if 'choices' in chunk and chunk['choices']:
                                        delta = chunk['choices'][0].get('delta', {})
                                        if 'content' in delta:
                                            content = delta['content']
                                            full_response += content
                                            if on_token:
                                                on_token(content)
                                except json.JSONDecodeError:
                                    pass
                    return full_response
                else:
                    data = await resp.json()
                    return data.get('choices', [{}])[0].get('message', {}).get('content', '')

    def _get_ram_gb(self) -> float:
        """Returns total system RAM in GB."""
        try:
            return psutil.virtual_memory().total / (1024 ** 3)
        except ImportError:
            return 8.0


if __name__ == '__main__':
    async def test_engine_router():
        settings = {
            'gemini_api_key': 'test-key-for-unit-test',
            'openrouter_api_key': '',
            'preferred_engine': 'auto'
        }

        router = EngineRouter(settings)
        status = await router.probe_engines()
        print('Engine status:', status.__dict__)

    asyncio.run(test_engine_router())