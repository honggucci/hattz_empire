"""
Test PowerShell pipe with UTF-8
"""
import subprocess
import tempfile
from pathlib import Path

# 테스트 프롬프트 (한글 포함)
prompt = "자 이제 유투브 자동 영상 제작에 대해 논의하고 싶어."

# 임시 파일 생성
prompt_file = Path(tempfile.gettempdir()) / "test_prompt.txt"
prompt_file.write_text(prompt, encoding="utf-8")

print(f"Prompt file: {prompt_file}")
print(f"Content: {prompt}")
print("=" * 80)

# PowerShell 명령 (간단한 echo로 테스트)
cmd = f"powershell -Command \"Get-Content -Raw -Encoding UTF8 '{prompt_file}'\""

print(f"Command: {cmd}")
print("=" * 80)

try:
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10
    )

    print(f"Exit Code: {result.returncode}")
    print(f"\nSTDOUT:")
    print(result.stdout)
    print(f"\nSTDERR:")
    print(result.stderr)

except Exception as e:
    print(f"ERROR: {e}")

finally:
    # cleanup
    if prompt_file.exists():
        prompt_file.unlink()
