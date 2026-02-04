import platform
import subprocess


def _os() -> str:
    return platform.system().lower()

# MacOS (AppleScript)
def _macos(cmd: str):
    script = f'''
    tell application "Spotify"
        {cmd}
    end tell
    '''
    subprocess.run(
        ["osascript", "-e", script],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# Linux (MPRIS / DBus)
def _linux(cmd: str):
    subprocess.run(
        [
            "dbus-send",
            "--print-reply",
            "--dest=org.mpris.MediaPlayer2.spotify",
            "/org/mpris/MediaPlayer2",
            f"org.mpris.MediaPlayer2.Player.{cmd}",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# Public API 
def play():
    if _os() == "darwin":
        _macos("play")
    elif _os() == "linux":
        _linux("Play")
    else:
        raise RuntimeError("Spotify control not supported on this OS")


def pause():
    if _os() == "darwin":
        _macos("pause")
    elif _os() == "linux":
        _linux("Pause")
    else:
        raise RuntimeError("Spotify control not supported on this OS")


def next_track():
    if _os() == "darwin":
        _macos("next track")
    elif _os() == "linux":
        _linux("Next")
    else:
        raise RuntimeError("Spotify control not supported on this OS")


def previous_track():
    if _os() == "darwin":
        _macos("previous track")
    elif _os() == "linux":
        _linux("Previous")
    else:
        raise RuntimeError("Spotify control not supported on this OS")