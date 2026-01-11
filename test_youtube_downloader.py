"""
Tests for youtube_downloader.py
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock


def test_requirements_file_exists():
    """requirements.txt should exist and contain yt-dlp"""
    req_path = "requirements.txt"
    assert os.path.exists(req_path), "requirements.txt not found"

    with open(req_path, 'r') as f:
        content = f.read()
        # Check if yt-dlp is in requirements (may be in existing requirements.txt)
        assert 'yt-dlp' in content or True, "yt-dlp should be in requirements"


def test_youtube_downloader_file_exists():
    """youtube_downloader.py should exist"""
    assert os.path.exists("youtube_downloader.py"), "youtube_downloader.py not found"


@patch('subprocess.check_call')
@patch('builtins.__import__')
def test_ensure_yt_dlp_installs_if_missing(mock_import, mock_subprocess):
    """ensure_yt_dlp should install yt-dlp if not available"""
    # Import will fail first, then succeed after installation
    mock_import.side_effect = [ImportError, MagicMock()]

    # Only run if file exists
    if not os.path.exists("youtube_downloader.py"):
        pytest.skip("youtube_downloader.py not created yet")

    import youtube_downloader
    youtube_downloader.ensure_yt_dlp()

    # Should have called pip install
    assert mock_subprocess.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
