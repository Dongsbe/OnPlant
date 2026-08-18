from __future__ import annotations

import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urljoin

import requests


DEFAULT_SERVER_URL = "http://192.168.10.110:5050"
DEFAULT_ROBOT_ID = "raspbot-a"
DEFAULT_MIC_DEVICE = "plughw:2,0"
DEFAULT_SPEAKER_DEVICE = "plughw:3,0"


def run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def speaker_card(speaker_device: str) -> str | None:
    if ":" in speaker_device:
        device = speaker_device
        if device.startswith("plughw:"):
            device = device.removeprefix("plughw:")
        if device.startswith("hw:"):
            device = device.removeprefix("hw:")
        card = device.split(",", 1)[0].strip()
        return card if card.isdigit() else None
    return None


def apply_speaker_volume(server: str, robot_id: str, speaker_device: str, control: str) -> None:
    try:
        response = requests.get(f"{server.rstrip('/')}/api/robots/{robot_id}/summary", timeout=2)
        response.raise_for_status()
        volume = int((response.json().get("config") or {}).get("speaker_volume", 60))
    except Exception:
        volume = 60
    volume = max(0, min(100, volume))
    card = speaker_card(speaker_device)
    if not card:
        return
    subprocess.run(
        ["amixer", "-c", card, "sset", control, f"{volume}%"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def record_voice(path: Path, seconds: float, mic_device: str) -> None:
    duration = max(1, int(math.ceil(seconds)))
    command = [
        "arecord",
        "-D",
        mic_device,
        "-f",
        "cd",
        "-d",
        str(duration),
        str(path),
    ]
    run_command(command)


def play_audio(path: Path, speaker_device: str) -> None:
    if path.suffix.lower() == ".wav":
        run_command(["aplay", "-D", speaker_device, str(path)])
        return

    for player in ("mpg123", "ffplay", "cvlc"):
        try:
            if player == "ffplay":
                subprocess.run(
                    [player, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
                    check=True,
                )
            elif player == "cvlc":
                subprocess.run([player, "--play-and-exit", str(path)], check=True)
            else:
                subprocess.run([player, "-q", str(path)], check=True)
            return
        except FileNotFoundError:
            continue
    raise RuntimeError("No MP3 player found. Install mpg123 on Raspberry Pi.")


def post_voice(server: str, robot_id: str, username: str, audio_path: Path) -> dict:
    url = f"{server.rstrip('/')}/api/robots/{robot_id}/voice/chat"
    with audio_path.open("rb") as audio_file:
        files = {"audio": ("voice.wav", audio_file, "audio/wav")}
        data = {"username": username}
        response = requests.post(url, data=data, files=files, timeout=90)
    response.raise_for_status()
    return response.json()


def download_audio(server: str, audio_url: str, output_path: Path) -> None:
    url = urljoin(server.rstrip("/") + "/", audio_url.lstrip("/"))
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    output_path.write_bytes(response.content)


def audio_suffix(audio_url: str) -> str:
    suffix = Path(audio_url.split("?", 1)[0]).suffix.lower()
    return suffix if suffix in {".wav", ".mp3"} else ".wav"


def run_voice_turn(
    args: argparse.Namespace,
    prompt: str,
    seconds: float,
    temp_path: Path,
    play_intents: set[str] | None = None,
) -> dict | None:
    voice_path = temp_path / "voice.wav"
    print(prompt)
    record_voice(voice_path, seconds, args.mic_device)

    print("Sending voice to server...")
    try:
        result = post_voice(args.server, args.robot_id, args.username, voice_path)
    except requests.RequestException as exc:
        print("voice request failed:", exc)
        return None

    print("transcript:", result.get("transcript"))
    print("reply:", result.get("reply"))
    print("intent:", result.get("intent"))
    if result.get("command"):
        print("command:", result["command"].get("command"))

    audio_url = result.get("audio_url")
    should_play = (
        audio_url
        and not args.no_play
        and (play_intents is None or result.get("intent") in play_intents)
    )
    if should_play:
        reply_path = temp_path / f"reply{audio_suffix(audio_url)}"
        download_audio(args.server, audio_url, reply_path)
        print("Playing AI voice reply...")
        apply_speaker_volume(args.server, args.robot_id, args.speaker_device, args.speaker_control)
        play_audio(reply_path, args.speaker_device)
    elif not audio_url and result.get("intent") not in {"no_speech"}:
        print("No TTS audio returned. Check server TTS setup.")

    return result


def run_loop(args: argparse.Namespace) -> int:
    print("Voice loop started. Commands only. Say: 오늘 상태 어때 / 멈춰 / 최적 조도 찾아줘. Press Ctrl+C to stop.")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        while True:
            result = run_voice_turn(
                args,
                f"Listening command {args.seconds:.1f}s. Say: 오늘 상태 어때",
                args.seconds,
                temp_path,
                play_intents={"robot_command", "sensor_query", "blocked_while_running"},
            )
            if not result:
                continue

            if result.get("intent") == "no_speech":
                print("No speech detected. Listening again.")
                continue

            if result.get("intent") in {"nickname", "ignored", "chat", "clarify"}:
                print("No command detected. Listening again.")
                continue


def main() -> int:
    parser = argparse.ArgumentParser(description="Record voice, send it to OnPlant server STT/LLM/TTS, and play reply.")
    parser.add_argument("--server", default=DEFAULT_SERVER_URL)
    parser.add_argument("--robot-id", default=DEFAULT_ROBOT_ID)
    parser.add_argument("--username", default="demo")
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--wake-seconds", type=float, default=2.0)
    parser.add_argument("--mic-device", default=DEFAULT_MIC_DEVICE)
    parser.add_argument("--speaker-device", default=DEFAULT_SPEAKER_DEVICE)
    parser.add_argument("--speaker-control", default="PCM")
    parser.add_argument("--no-play", action="store_true")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    if args.loop:
        return run_loop(args)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_voice_turn(
            args,
            f"Recording {args.seconds:.1f}s. Say: 동스비 오늘 상태 어때",
            args.seconds,
            temp_path,
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"command failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
