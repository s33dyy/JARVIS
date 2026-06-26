generate_cad_prototype_tool = {
    "name": "generate_cad_prototype",
    "description": "Generates a 3D wireframe prototype based on a user's description. Use this when the user asks to 'visualize', 'prototype', 'create a wireframe', or 'design' something in 3D.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {
                "type": "STRING",
                "description": "The user's description of the object to prototype."
            }
        },
        "required": ["prompt"]
    }
}




write_file_tool = {
    "name": "write_file",
    "description": "Writes content to a file at the specified path. Overwrites if exists.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "The path of the file to write to."
            },
            "content": {
                "type": "STRING",
                "description": "The content to write to the file."
            }
        },
        "required": ["path", "content"]
    }
}

read_directory_tool = {
    "name": "read_directory",
    "description": "Lists the contents of a directory.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "The path of the directory to list."
            }
        },
        "required": ["path"]
    }
}

read_file_tool = {
    "name": "read_file",
    "description": "Reads the content of a file.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "The path of the file to read."
            }
        },
        "required": ["path"]
    }
}

run_terminal_tool = {
    "name": "run_terminal",
    "description": "Runs a shell command in the terminal and returns the output. Use for file operations, git commands, system utilities, etc. Sudo and destructive commands are blocked.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "command": {
                "type": "STRING",
                "description": "The shell command to execute (e.g. 'ls -la', 'git status', 'python --version')."
            }
        },
        "required": ["command"]
    }
}

run_python_code_tool = {
    "name": "run_python_code",
    "description": "Executes Python code in an isolated process and returns stdout/stderr. Use for data analysis, calculations, quick scripts, testing code snippets.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "code": {
                "type": "STRING",
                "description": "The Python source code to execute."
            }
        },
        "required": ["code"]
    }
}

install_package_tool = {
    "name": "install_package",
    "description": "Installs a Python package using pip. Use when a required library is missing.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "package_name": {
                "type": "STRING",
                "description": "The pip package name to install (e.g. 'requests', 'numpy>=1.24')."
            }
        },
        "required": ["package_name"]
    }
}

tools_list = [{"function_declarations": [
    generate_cad_prototype_tool,
    write_file_tool,
    read_directory_tool,
    read_file_tool,
    run_terminal_tool,
    run_python_code_tool,
    install_package_tool,
]}]


