"""
Test Claude CLI with discuss mode prompt
"""
import subprocess

system_prompt = """You are a deep thinker and strategic advisor.
Your role is to engage in thoughtful dialogue and help discover insights through discussion.

Focus on:
- Asking probing questions to clarify intent
- Identifying underlying assumptions
- Exploring multiple perspectives
- Suggesting strategic directions

Be conversational but insightful. Challenge ideas constructively."""

user_message = "자 이제 유투브 자동 영상 제작에 대해 논의하고 싶어."

# Claude CLI 명령 구성 (profile=None, 즉 no persona)
cmd = f'claude --no-profile "{user_message}"'

print(f"Executing: {cmd}")
print("=" * 80)

try:
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60
    )

    print(f"Exit Code: {result.returncode}")
    print(f"STDOUT ({len(result.stdout)} chars):")
    print(result.stdout)
    print(f"\nSTDERR:")
    print(result.stderr)

except subprocess.TimeoutExpired:
    print("TIMEOUT!")
except Exception as e:
    print(f"ERROR: {e}")
