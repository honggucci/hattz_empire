"""
API 연결 테스트 - Claude, GPT, Gemini
"""
import os
from dotenv import load_dotenv

load_dotenv()

def test_openai():
    """OpenAI GPT 테스트"""
    print("\n[1] OpenAI GPT 테스트...")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        response = client.chat.completions.create(
            model="gpt-4o-mini",  # 저렴한 모델로 테스트
            messages=[{"role": "user", "content": "Say 'GPT OK' in 2 words"}],
            max_tokens=10
        )
        result = response.choices[0].message.content
        print(f"  [OK] OpenAI: {result}")
        return True
    except Exception as e:
        print(f"  [FAIL] OpenAI: {e}")
        return False


def test_anthropic():
    """Anthropic Claude 테스트"""
    print("\n[2] Anthropic Claude 테스트...")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        response = client.messages.create(
            model="claude-3-haiku-20240307",  # 저렴한 모델로 테스트
            max_tokens=10,
            messages=[{"role": "user", "content": "Say 'Claude OK' in 2 words"}]
        )
        result = response.content[0].text
        print(f"  [OK] Anthropic: {result}")
        return True
    except Exception as e:
        print(f"  [FAIL] Anthropic: {e}")
        return False


def test_google():
    """Google Gemini 테스트"""
    print("\n[3] Google Gemini 테스트...")
    try:
        from google import genai
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Say 'Gemini OK' in 2 words"
        )
        result = response.text
        print(f"  [OK] Google: {result.strip()}")
        return True
    except Exception as e:
        print(f"  [FAIL] Google: {e}")
        return False


if __name__ == "__main__":
    print("="*50)
    print("HATTZ EMPIRE - API 연결 테스트")
    print("="*50)

    results = {
        "OpenAI (GPT)": test_openai(),
        "Anthropic (Claude)": test_anthropic(),
        "Google (Gemini)": test_google(),
    }

    print("\n" + "="*50)
    print("결과 요약:")
    print("="*50)
    for name, ok in results.items():
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {name}: {status}")

    all_ok = all(results.values())
    print("\n" + ("All APIs connected!" if all_ok else "Some APIs failed"))
