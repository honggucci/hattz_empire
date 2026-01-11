"""
Claude CLI 직접 테스트 (v2.6.5)
"""
import subprocess

# Node.js + cli.js 직접 실행
node_path = r"C:\Program Files\nodejs\node.exe"
cli_js = r"C:\Users\hahonggu\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\cli.js"

cmd = [node_path, cli_js, '--print', '--model', 'claude-opus-4-5-20251101', '--dangerously-skip-permissions']

prompt = "안녕하세요. 간단한 테스트입니다."

print(f"Command: {' '.join(cmd)}")
print(f"Prompt: {prompt}")
print("=" * 80)

try:
    result = subprocess.run(
        cmd,
        input=prompt.encode('utf-8'),
        capture_output=True,
        timeout=30
    )

    stdout = result.stdout.decode('utf-8', errors='replace')
    stderr = result.stderr.decode('utf-8', errors='replace')

    print(f"Exit Code: {result.returncode}")
    print(f"\nSTDOUT ({len(stdout)} chars):")
    print(stdout)
    print(f"\nSTDERR:")
    print(stderr)

except Exception as e:
    print(f"ERROR: {e}")
