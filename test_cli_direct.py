"""
Direct CLI test to capture stderr output
"""
import subprocess
import tempfile
from pathlib import Path

# Build simple prompt
prompt = "Say hello in one sentence."
system_prompt = "You are a helpful assistant."
full_prompt = f"{system_prompt}\n\nUser: {prompt}\n\nAssistant:"

# Save to temp file
prompt_file = Path(tempfile.gettempdir()) / "test_prompt.txt"
prompt_file.write_text(full_prompt, encoding="utf-8")

# Build CLI command (using reviewer profile for Sonnet 4.5)
cli_path = '"C:\\Program Files\\nodejs\\node.exe" "C:\\Users\\hahonggu\\AppData\\Roaming\\npm\\node_modules\\@anthropic-ai\\claude-code\\cli.js"'
model = "claude-sonnet-4-20250514"  # Sonnet 4 (not 4.5)
import uuid
session_id = str(uuid.uuid4())

cmd = f'{cli_path} --print --model {model} --session-id {session_id} --dangerously-skip-permissions < "{prompt_file}"'

print(f"Command: {cmd}\n")
print("=" * 80)

# Execute
proc = subprocess.Popen(
    cmd,
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    errors="replace"
)

stdout, stderr = proc.communicate(timeout=30)

print("STDOUT:")
print(stdout)
print("\n" + "=" * 80)
print("STDERR:")
print(stderr)
print("\n" + "=" * 80)
print(f"Return code: {proc.returncode}")

# Cleanup
prompt_file.unlink()
