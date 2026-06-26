import os
import json
import asyncio
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing import List, Optional


def _get_cad_python_env():
    """Return (python_exe, env_dict) for running build123d scripts in subprocess."""
    import sys
    env = os.environ.copy()

    # On macOS, ensure DYLD_LIBRARY_PATH includes Homebrew expat (fixes pyexpat)
    if sys.platform == "darwin":
        expat_lib = "/opt/homebrew/opt/expat/lib"
        existing = env.get("DYLD_LIBRARY_PATH", "")
        if expat_lib not in existing:
            env["DYLD_LIBRARY_PATH"] = f"{expat_lib}:{existing}" if existing else expat_lib

    # In PyInstaller bundle, sys.executable is the frozen binary, not a Python interpreter
    if getattr(sys, 'frozen', False):
        for candidate in [
            "/opt/homebrew/bin/python3",
            "/usr/bin/python3",
            "/usr/local/bin/python3",
        ]:
            if os.path.isfile(candidate):
                return candidate, env
        return sys.executable, env
    return sys.executable, env

load_dotenv()

class CadAgent:
    def __init__(self, on_thought=None, on_status=None, engine_router=None):
        api_key = self._get_api_key()
        self.client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key) if api_key else None
        # Using Gemini 2.0 Flash — high free-tier quota, excellent code generation
        self.model = "gemini-2.0-flash"
        self.on_thought = on_thought  # Callback for streaming thoughts 
        self.on_status = on_status  # Callback for retry status info
        self._engine_router = engine_router  # EngineRouter singleton for fallback

        self.system_instruction = """
You are a Python-based 3D CAD Engineer using the `build123d` library.
Your goal is to write a Python script that generates a 3D model based on the user's request.

Requirements:
1. Start with `from build123d import *`.
2. Include `import numpy as np` if you use any numpy functions (like `np.sign`, `np.pi`).
3. You MUST assign the final object to a variable named `result_part`.
4. If you create a sketch or line, extrude it to make it a solid `Part`.
5. The model should be centered at (0,0,0) and have reasonable dimensions (mm).
6. **IMPORTANT**: Do NOT use old or PascalCase function names for core operations.
   - Use `make_face()` instead of `MakeFace()`.
   - Use `extrude()` instead of `Extrude()`.
   - Use `fillet()` instead of `Fillet()`.
   - Use `chamfer()` instead of `Chamfer()`.
   - Use `revolve()` instead of `Revolve()`.
   - Use `loft()` instead of `Loft()`.
   - Use `sweep()` instead of `Sweep()`.
   - Use `offset()` instead of `Offset()`.
   - generally prefer lowercase builder methods inside contexts.

7. **Vector Access**: Do NOT access vector components like `v.X`, `v.Y`, `v.Z` unless you are sure they exist (use `v.X` etc on Vector objects, but ensure they are Vectors).
8. **Final Output**: The script MUST end by exporting the final part to an STL file named 'output.stl'.
   - `export_stl(result_part, 'output.stl')`

9. **Robustness**: Operations like `fillet()` and `chamfer()` will crash if the radius is too large for the geometry.
   - Use conservative values (e.g., 0.5mm to 2mm) unless you are certain of the dimensions.
   - If a fillet is purely aesthetic, keep it small to ensure success.

Example Script:
```python
from build123d import *

with BuildPart() as p:
    Box(10, 10, 10)
    Fillet(p.edges(), radius=1)

result_part = p.part
export_stl(result_part, 'output.stl')
```
"""

    @staticmethod
    def _get_api_key() -> str:
        """Read API key from env var (set by server.py from settings.json)."""
        return os.getenv('GEMINI_API_KEY', '')

    def _init_client(self):
        """Re-initialize Gemini client with current API key from env."""
        api_key = self._get_api_key()
        if api_key:
            self.client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
        else:
            self.client = None

    async def generate_prototype(self, prompt: str, output_dir: Optional[str] = None):
        """
        Generates 3D geometry by asking Gemini for a script, then running it LOCALLY.
        Args:
            prompt: User's description of the model to generate.
            output_dir: Directory to save the script and STL. If None, uses temp dir.
        """
        print(f"[CadAgent DEBUG] [START] Generation started for: '{prompt}'")
        
        # If no Gemini client, fall back to engine router
        if not self.client:
            print("[CadAgent DEBUG] No Gemini client — using engine router fallback")
            if self._engine_router:
                return await self._generate_via_engine_router(prompt, output_dir)
            else:
                return await self._generate_with_ollama(prompt, output_dir)
        
        try:
            # Use provided output_dir or fall back to temp
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                work_dir = output_dir
            else:
                import tempfile
                work_dir = tempfile.gettempdir()
            
            # Generate timestamped filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_stl = os.path.join(work_dir, f"output_{timestamp}.stl")
            script_path = os.path.join(work_dir, "current_design.py")

            max_retries = 3
            current_prompt = f"You are a build123d expert. Write a generic python script to create a 3D model of: {prompt}. Ensure you export to 'output.stl'. Unscaled."
            
            for attempt in range(max_retries):
                print(f"[CadAgent DEBUG] Attempt {attempt + 1}/{max_retries}")
                
                # Emit status update
                if self.on_status:
                    status_info = {
                        "status": "generating" if attempt == 0 else "retrying",
                        "attempt": attempt + 1,
                        "max_attempts": max_retries,
                        "error": None
                    }
                    self.on_status(status_info)
                
                # 1. Ask Gemini for the code with streaming and thinking
                raw_content = ""
                stream = await self.client.aio.models.generate_content_stream(
                    model=self.model,
                    contents=current_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_instruction,
                        temperature=1.0,
                        thinking_config=types.ThinkingConfig(include_thoughts=True)
                    )
                )
                async for chunk in stream:
                    if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                        for part in chunk.candidates[0].content.parts:
                            if not part.text:
                                continue
                            elif part.thought:
                                # Stream thought to callback
                                if self.on_thought:
                                    self.on_thought(part.text)
                            else:
                                # Accumulate answer text
                                raw_content += part.text
                
                if not raw_content:
                    print("[CadAgent DEBUG] [ERR] Empty response from model.")
                    return None

                # 2. Extract Code Block
                import re
                code_match = re.search(r'```python(.*?)```', raw_content, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                else:
                    # Fallback: assume entire text is code if no blocks, or fail
                    print("[CadAgent DEBUG] [WARN] No ```python block found. Trying heuristic...")
                    if "import build123d" in raw_content:
                        code = raw_content
                    else:
                        print("[CadAgent DEBUG] [ERR] Could not extract python code.")
                        return None
                
                # 3. Save to Local File in cad_outputs folder
                # Fix for Windows paths in python strings: escape backslashes
                safe_output_path = output_stl.replace("\\", "\\\\")
                
                with open(script_path, "w") as f:
                    # Inject output path into the script
                    code_with_path = code.replace("output.stl", safe_output_path)
                    f.write(code_with_path)
                    
                print(f"[CadAgent DEBUG] [EXEC] Running local script: {script_path}")

                # 4. Execute Locally
                import subprocess
                _python_exe, _env = _get_cad_python_env()

                try:
                    proc = await asyncio.to_thread(
                        subprocess.run,
                        [_python_exe, script_path],
                        capture_output=True,
                        text=True,
                        env=_env
                    )
                    stdout, stderr = proc.stdout, proc.stderr
                except Exception as e:
                     print(f"[CadAgent DEBUG] [ERR] Subprocess run failed: {e}")
                     proc = type('obj', (object,), {'returncode': 1})
                     stdout = ""
                     stderr = str(e)
                
                if proc.returncode != 0:
                    error_msg = stderr
                    # Extract a concise error message for display
                    error_lines = error_msg.strip().split('\n')
                    short_error = error_lines[-1][:100] if error_lines else "Unknown error"
                    print(f"[CadAgent DEBUG] [ERR] Script Execution Failed:\n{error_msg}")
                    
                    # Emit retry status with error
                    if self.on_status:
                        self.on_status({
                            "status": "retrying",
                            "attempt": attempt + 1,
                            "max_attempts": max_retries,
                            "error": short_error
                        })
                    
                    # Preparing feedback for next attempt
                    current_prompt = f"""
The Python script you generated failed to execute with the following error:
{error_msg}

Please fix the code to resolve this error. Return the full corrected script. 
Ensure you still export to 'output.stl'.
Original request: {prompt}
"""
                    continue # Retry loop
                
                print(f"[CadAgent DEBUG] [OK] Script executed successfully.")
                
                # 5. Read Output
                if os.path.exists(output_stl):
                    print(f"[CadAgent DEBUG] [file] '{output_stl}' found.")
                    with open(output_stl, "rb") as f:
                        stl_data = f.read()
                        
                    import base64
                    b64_stl = base64.b64encode(stl_data).decode('utf-8')
                    
                    return {
                        "format": "stl",
                        "data": b64_stl,
                        "file_path": output_stl
                    }
                else:
                     print(f"[CadAgent DEBUG] [ERR] '{output_stl}' was not generated.")
                     # If script ran but no output, treat as failure and retry?
                     # Ideally yes.
                     current_prompt = f"The script executed successfully but 'output.stl' was not found. Ensure you call `export_stl(result_part, 'output.stl')` at the end."
                     continue

            # If loop finishes without success — try Ollama fallback
            print("[CadAgent DEBUG] [ERR] All Gemini attempts failed — trying Ollama fallback...")
            if self.on_status:
                self.on_status({"status": "retrying", "attempt": max_retries, "max_attempts": max_retries + 1,
                                "error": "Gemini quota hit — switching to local AI"})
            result = await self._generate_with_ollama(prompt, output_dir)
            if result:
                return result
            if self.on_status:
                self.on_status({"status": "failed", "attempt": max_retries, "max_attempts": max_retries,
                                "error": "All generation attempts failed"})
            return None

        except Exception as e:
            err_str = str(e)
            print(f"CadAgent Error: {e}")
            import traceback
            traceback.print_exc()
            # ── Ollama fallback on quota / auth errors ──
            if any(k in err_str for k in ["429", "quota", "RESOURCE_EXHAUSTED", "API key", "401", "403"]):
                print("[CadAgent] Gemini unavailable — trying Ollama fallback...")
                result = await self._generate_with_ollama(prompt, output_dir)
                if result:
                    return result
            return None

    async def _generate_with_ollama(self, prompt: str, output_dir: str = None) -> dict:
        """Fallback: generate CAD code using EngineRouter (Ollama/MLX/etc)."""
        try:
            # Use EngineRouter if available, otherwise fall back to direct ollama_manager
            if self._engine_router:
                return await self._generate_via_engine_router(prompt, output_dir)
            else:
                return await self._generate_via_ollama_manager(prompt, output_dir)
        except Exception as e:
            print(f"[CadAgent/Ollama] Fallback error: {e}")
            return None

    async def _generate_via_engine_router(self, prompt: str, output_dir: str = None) -> dict:
        """Generate CAD code using the EngineRouter for automatic fallback."""
        import re, base64
        from datetime import datetime

        if self.on_status:
            self.on_status({"status": "generating", "attempt": 1, "max_attempts": 1,
                            "error": None, "provider": "engine_router"})

        code_prompt = (
            f"Write a Python script using the build123d library to create a 3D model of: {prompt}. "
            "Requirements: start with 'from build123d import *', assign final object to 'result_part', "
            "export with: export_stl(result_part, 'output.stl'). Return ONLY the Python code in a ```python block."
        )

        raw = await self._engine_router.complete(
            prompt=code_prompt,
            system=self.system_instruction,
            task_type='code',
            temperature=1.0,
            max_tokens=4096,
        )
        if not raw:
            print("[CadAgent/EngineRouter] Empty response.")
            return None

        code_match = re.search(r'```python(.*?)```', raw, re.DOTALL)
        if code_match:
            code = code_match.group(1).strip()
        elif "from build123d" in raw:
            code = raw
        else:
            print("[CadAgent/EngineRouter] Could not extract code from response.")
            return None

        return await self._execute_cad_script(code, prompt, output_dir, provider="engine_router")

    async def _generate_via_ollama_manager(self, prompt: str, output_dir: str = None) -> dict:
        """Fallback: generate CAD code using ollama_manager directly."""
        try:
            import ollama_manager
            model = await ollama_manager.ensure_ready(
                "code",
                on_status=lambda msg: print(f"[CadAgent/Ollama] {msg}")
            )
            if not model:
                print("[CadAgent/Ollama] No local model available.")
                return None

            if self.on_status:
                self.on_status({"status": "generating", "attempt": 1, "max_attempts": 1,
                                "error": None, "provider": "local"})

            code_prompt = (
                f"Write a Python script using the build123d library to create a 3D model of: {prompt}. "
                "Requirements: start with 'from build123d import *', assign final object to 'result_part', "
                "export with: export_stl(result_part, 'output.stl'). Return ONLY the Python code in a ```python block."
            )

            raw = await ollama_manager.generate_text(model, code_prompt, system=self.system_instruction)
            if not raw:
                return None

            import re
            code_match = re.search(r'```python(.*?)```', raw, re.DOTALL)
            if code_match:
                code = code_match.group(1).strip()
            elif "from build123d" in raw:
                code = raw
            else:
                print("[CadAgent/Ollama] Could not extract code from response.")
                return None

            return await self._execute_cad_script(code, prompt, output_dir, provider="local")
        except Exception as e:
            print(f"[CadAgent/Ollama] Direct ollama_manager error: {e}")
            return None

    async def _execute_cad_script(self, code: str, prompt: str, output_dir: str = None, provider: str = "unknown") -> dict:
        """Shared helper: save CAD script to disk, execute it, return STL data."""
        import re, base64
        from datetime import datetime

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            work_dir = output_dir
        else:
            import tempfile
            work_dir = tempfile.gettempdir()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_stl = os.path.join(work_dir, f"output_{timestamp}.stl")
        script_path = os.path.join(work_dir, "current_design_local.py")
        safe_output_path = output_stl.replace("\\", "\\\\")
        code_with_path = code.replace("output.stl", safe_output_path)

        with open(script_path, "w") as f:
            f.write(code_with_path)

        import subprocess
        _python_exe, _env = _get_cad_python_env()

        proc = await asyncio.to_thread(
            subprocess.run, [_python_exe, script_path],
            capture_output=True, text=True, env=_env
        )
        if proc.returncode != 0:
            print(f"[CadAgent/{provider}] Script failed: {proc.stderr[-500:]}")
            return None

        if os.path.exists(output_stl):
            with open(output_stl, "rb") as f:
                stl_data = f.read()
            b64_stl = base64.b64encode(stl_data).decode('utf-8')
            print(f"[CadAgent/{provider}] CAD generation succeeded!")
            return {"format": "stl", "data": b64_stl, "file_path": output_stl, "provider": provider}
        return None

    async def iterate_prototype(self, prompt: str, output_dir: Optional[str] = None):

        """
        Iterates on the existing design by reading 'current_design.py' and applying changes.
        Args:
            prompt: User's description of the changes to make.
            output_dir: Directory containing existing script and where to save new STL.
        """
        print(f"[CadAgent DEBUG] [START] Iteration started for: '{prompt}'")
        
        # If no Gemini client, fall back to fresh generation via engine router
        if not self.client:
            print("[CadAgent DEBUG] No Gemini client for iteration — using engine router fallback")
            if self._engine_router:
                return await self._generate_via_engine_router(prompt, output_dir)
            else:
                return await self.generate_prototype(prompt, output_dir)
        
        # Use provided output_dir or fall back to temp
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            work_dir = output_dir
        else:
            import tempfile
            work_dir = tempfile.gettempdir()
        
        # Generate timestamped filename for the output
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        script_path = os.path.join(work_dir, "current_design.py")
        output_stl = os.path.join(work_dir, f"output_{timestamp}.stl")
        
        existing_code = ""
        
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                existing_code = f.read()
            
            # Sanitize existing code: replace any absolute paths with 'output.stl'
            # This prevents the LLM from seeing/reproducing Windows paths that cause Unicode escape errors
            import re
            # Match both escaped (\\) and unescaped (\) Windows paths to output.stl
            existing_code = re.sub(
                r"['\"]C:\\\\?Users\\\\?[^'\"]+\\\\?output[^'\"]*\.stl['\"]",
                "'output.stl'",
                existing_code
            )
            # Also handle forward-slash variants
            existing_code = re.sub(
                r"['\"]C:/Users/[^'\"]+/output[^'\"]*\.stl['\"]",
                "'output.stl'",
                existing_code
            )
        else:
             print("[CadAgent DEBUG] [WARN] No existing script found. Falling back to fresh generation.")
             return await self.generate_prototype(prompt)

        try:

            max_retries = 3
            current_prompt = f"""
You are iterating on an existing 3D model script.

Current Python Code:
```python
{existing_code}
```

User Request: {prompt}

Task: Rewrite the code to satisfy the user's request while maintaining the rest of the model structure.
Ensure you still export to 'output.stl'.
"""
            
            for attempt in range(max_retries):
                print(f"[CadAgent DEBUG] Iteration Attempt {attempt + 1}/{max_retries}")
                
                # Emit status update
                if self.on_status:
                    status_info = {
                        "status": "generating" if attempt == 0 else "retrying",
                        "attempt": attempt + 1,
                        "max_attempts": max_retries,
                        "error": None
                    }
                    self.on_status(status_info)
                
                # 1. Ask Gemini for the code with streaming and thinking
                raw_content = ""
                stream = await self.client.aio.models.generate_content_stream(
                    model=self.model,
                    contents=current_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_instruction,
                        temperature=1.0,
                        thinking_config=types.ThinkingConfig(include_thoughts=True)
                    )
                )
                async for chunk in stream:
                    if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                        for part in chunk.candidates[0].content.parts:
                            if not part.text:
                                continue
                            elif part.thought:
                                # Stream thought to callback
                                if self.on_thought:
                                    self.on_thought(part.text)
                            else:
                                # Accumulate answer text
                                raw_content += part.text
                
                if not raw_content:
                    print("[CadAgent DEBUG] [ERR] Empty response from model.")
                    return None

                # 2. Extract Code Block
                import re
                code_match = re.search(r'```python(.*?)```', raw_content, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                else:
                    # Fallback: assume entire text is code if no blocks, or fail
                    print("[CadAgent DEBUG] [WARN] No ```python block found. Trying heuristic...")
                    if "import build123d" in raw_content:
                        code = raw_content
                    else:
                        print("[CadAgent DEBUG] [ERR] Could not extract python code.")
                        return None
                
                # 3. Save to Local File in cad_outputs folder
                # Overwrite the script so the next iteration builds on this one
                
                # Fix for Windows paths in python strings: escape backslashes
                safe_output_path = output_stl.replace("\\", "\\\\")
                
                with open(script_path, "w") as f:
                    # Inject output path into the script
                    code_with_path = code.replace("output.stl", safe_output_path)
                    f.write(code_with_path)
                    
                print(f"[CadAgent DEBUG] [EXEC] Running local script: {script_path}")
                
                # 4. Execute Locally
                import subprocess
                _python_exe, _env = _get_cad_python_env()

                try:
                    proc = await asyncio.to_thread(
                        subprocess.run,
                        [_python_exe, script_path],
                        capture_output=True,
                        text=True,
                        env=_env
                    )
                    stdout, stderr = proc.stdout, proc.stderr
                except Exception as e:
                    print(f"[CadAgent DEBUG] [ERR] Subprocess run failed: {e}")
                    proc = type('obj', (object,), {'returncode': 1})()
                    stdout = ""
                    stderr = str(e)
                
                if proc.returncode != 0:
                    error_msg = stderr
                    print(f"[CadAgent DEBUG] [ERR] Script Execution Failed:\n{error_msg}")
                    
                    # Preparing feedback for next attempt
                    current_prompt = f"""
The updated Python script you generated failed to execute with the following error:
{error_msg}

Please fix the code to resolve this error. Return the full corrected script. 
Ensure you still export to 'output.stl'.
"""
                    continue # Retry loop
                
                print(f"[CadAgent DEBUG] [OK] Script executed successfully.")
                
                # 5. Read Output
                if os.path.exists(output_stl):
                    print(f"[CadAgent DEBUG] [file] '{output_stl}' found.")
                    with open(output_stl, "rb") as f:
                        stl_data = f.read()
                        
                    import base64
                    b64_stl = base64.b64encode(stl_data).decode('utf-8')
                    
                    return {
                        "format": "stl",
                        "data": b64_stl,
                        "file_path": output_stl
                    }
                else:
                     print(f"[CadAgent DEBUG] [ERR] '{output_stl}' was not generated.")
                     current_prompt = f"The script executed successfully but '{output_stl}' was not found. Ensure you call `export_stl(result_part, 'output.stl')` at the end."
                     continue

            # If loop finishes without success
            print("[CadAgent DEBUG] [ERR] All attempts failed.")
            if self.on_status:
                self.on_status({
                    "status": "failed",
                    "attempt": max_retries,
                    "max_attempts": max_retries,
                    "error": "All iteration attempts failed"
                })
            return None

        except Exception as e:
            print(f"CadAgent Error: {e}")
            import traceback
            traceback.print_exc()
            return None

