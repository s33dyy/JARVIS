import os
import shutil
import urllib.request
import zipfile
import subprocess
from pathlib import Path

def main():
    workspace = Path(__file__).parent.resolve()
    dist_dir = workspace / "dist" / "JARVIS"
    site_packages = dist_dir / "site-packages"
    temp_wheels = workspace / "temp_wheels"
    
    print("Cleaning up old build directories...")
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if temp_wheels.exists():
        shutil.rmtree(temp_wheels)
        
    dist_dir.mkdir(parents=True, exist_ok=True)
    site_packages.mkdir(parents=True, exist_ok=True)
    temp_wheels.mkdir(parents=True, exist_ok=True)
    
    # 1. Download Windows embeddable Python
    python_zip = workspace / "python-3.11.9-embed-amd64.zip"
    if not python_zip.exists():
        print("Downloading Windows embeddable Python 3.11.9...")
        url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
        urllib.request.urlretrieve(url, python_zip)
    else:
        print("Using cached Python zip.")
        
    # 2. Extract Python embeddable zip
    print("Extracting Python embeddable zip...")
    with zipfile.ZipFile(python_zip, 'r') as zip_ref:
        zip_ref.extractall(dist_dir)
        
    # 3. Modify python311._pth
    pth_file = dist_dir / "python311._pth"
    if pth_file.exists():
        print("Modifying python311._pth...")
        lines = pth_file.read_text().splitlines()
        # Add site-packages and enable site module
        new_lines = []
        for line in lines:
            if line.strip() == "#import site":
                new_lines.append("import site")
            else:
                new_lines.append(line)
            if line.strip() == ".":
                new_lines.append("site-packages")
        pth_file.write_text("\n".join(new_lines) + "\n")
        
    # 4. Download Windows amd64 wheels
    print("Downloading Windows amd64 wheels using pip...")
    pip_cmd = [
        str(workspace / ".venv" / "bin" / "python"),
        "-m", "pip", "download",
        "--dest", str(temp_wheels),
        "--platform", "win_amd64",
        "--only-binary=:all:",
        "--implementation", "cp",
        "--python-version", "311",
        "-r", str(workspace / "requirements.txt")
    ]
    subprocess.run(pip_cmd, check=True)
    
    # 5. Extract all wheels to site-packages
    print("Extracting wheels to site-packages...")
    for wheel_path in temp_wheels.glob("*.whl"):
        print(f"Extracting {wheel_path.name}...")
        with zipfile.ZipFile(wheel_path, 'r') as zip_ref:
            # Extract everything to site-packages
            zip_ref.extractall(site_packages)
            
    # 6. Copy jarvis_*.py files to dist/JARVIS/
    print("Copying jarvis_*.py files...")
    for py_file in workspace.glob("jarvis_*.py"):
        print(f"Copying {py_file.name}...")
        shutil.copy2(py_file, dist_dir / py_file.name)
        
    # 7. Copy resource directories
    for folder in ["assets", "configs", "tools"]:
        src_folder = workspace / folder
        if src_folder.exists():
            print(f"Copying folder {folder}...")
            dest_folder = dist_dir / folder
            if dest_folder.exists():
                shutil.rmtree(dest_folder)
            shutil.copytree(src_folder, dest_folder)
            
    # 8. Write and compile Go runner
    runner_go = workspace / "runner.go"
    print("Writing Go runner.go...")
    go_code = """package main

import (
	"os"
	"os/exec"
	"path/filepath"
)

func main() {
	exePath, err := os.Executable()
	if err != nil {
		return
	}
	dir := filepath.Dir(exePath)

	pythonw := filepath.Join(dir, "pythonw.exe")
	script := filepath.Join(dir, "jarvis_ui.py")

	cmd := exec.Command(pythonw, script)
	cmd.Start()
}
"""
    runner_go.write_text(go_code)
    
    print("Compiling Go runner.go for Windows (amd64)...")
    env = os.environ.copy()
    env["GOOS"] = "windows"
    env["GOARCH"] = "amd64"
    go_build_cmd = [
        "go", "build",
        "-ldflags=-H windowsgui",
        "-o", str(dist_dir / "JARVIS.exe"),
        str(runner_go)
    ]
    subprocess.run(go_build_cmd, env=env, check=True)
    
    # 9. Clean up temporary files
    print("Cleaning up temporary build files...")
    if temp_wheels.exists():
        shutil.rmtree(temp_wheels)
    if runner_go.exists():
        runner_go.unlink()
    if python_zip.exists():
        python_zip.unlink()
        
    print("\nSUCCESS! Self-contained Windows distribution built at dist/JARVIS/")
    print("Run JARVIS.exe on Windows to launch.")

if __name__ == "__main__":
    main()
