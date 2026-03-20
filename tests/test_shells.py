import os
from unittest.mock import patch

from ai_cli_api.shells import detect_bash_path, to_bash_path


def test_to_bash_path_converts_windows_drive():
    assert to_bash_path("C:\\Users\\test\\project") == "/c/Users/test/project"


def test_to_bash_path_converts_uppercase_drive():
    assert to_bash_path("D:\\data") == "/d/data"


def test_to_bash_path_passes_unix_path_through():
    assert to_bash_path("/home/user/project") == "/home/user/project"


def test_to_bash_path_normalizes_backslashes():
    assert to_bash_path("some\\path\\here") == "some/path/here"


def test_detect_bash_path_uses_override():
    assert detect_bash_path("/custom/bash") == "/custom/bash"


def test_detect_bash_path_non_windows_uses_which():
    with patch("ai_cli_api.shells.os") as mock_os, \
         patch("ai_cli_api.shells.shutil") as mock_shutil:
        mock_os.name = "posix"
        mock_shutil.which.return_value = "/usr/bin/bash"
        result = detect_bash_path(None)
        assert result == "/usr/bin/bash"


def test_detect_bash_path_windows_checks_git_bash():
    with patch("ai_cli_api.shells.os") as mock_os, \
         patch("ai_cli_api.shells.Path") as mock_path_cls:
        mock_os.name = "nt"
        # First candidate exists
        instance = mock_path_cls.return_value
        instance.exists.return_value = True
        result = detect_bash_path(None)
        assert "bash" in result.lower()
