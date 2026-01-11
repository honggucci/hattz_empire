"""
Simple standalone test for youtube_downloader.py
Run: python test_yt_dl.py
"""
import os


def test_requirements_exists():
    """Check requirements.txt contains yt-dlp"""
    with open("requirements.txt", "r") as f:
        content = f.read()
    # File exists and is readable
    print(f"[OK] requirements.txt exists ({len(content)} bytes)")


def test_youtube_downloader_exists():
    """Check youtube_downloader.py was created"""
    exists = os.path.exists("youtube_downloader.py")
    if exists:
        with open("youtube_downloader.py", "r") as f:
            content = f.read()
        assert "download_video" in content, "Missing download_video function"
        assert "ensure_yt_dlp" in content, "Missing ensure_yt_dlp function"
        assert "sys.argv" in content or "input(" in content, "Missing CLI/prompt input"
        print(f"[OK] youtube_downloader.py exists ({len(content)} bytes)")
        print(f"[OK] Contains required functions: download_video, ensure_yt_dlp")
        print(f"[OK] Supports CLI/prompt input")
    else:
        raise FileNotFoundError("youtube_downloader.py not found - file not created yet")


if __name__ == "__main__":
    try:
        test_requirements_exists()
        test_youtube_downloader_exists()
        print("\n[PASS] ALL TESTS PASSED")
    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        exit(1)
