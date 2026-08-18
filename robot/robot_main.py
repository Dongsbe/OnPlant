from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from Raspbot_Lib import Raspbot
from hardware.raspbot_driver import RaspbotDriver


DEFAULT_SERVER_URL = "http://192.168.10.110:5050"
DEFAULT_ROBOT_ID = "raspbot-a"
DEFAULT_SPEAKER_DEVICE = "plughw:3,0"

START_KEY = 16
STOP_KEY = 17
STATUS_KEY = 18
SHUTDOWN_KEY = 9
IGNORE_KEYS = {0, 65, 255}


class RobotMain:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project_dir = Path(args.project_dir).resolve()
        self.server = args.server.rstrip("/")
        self.robot_id = args.robot_id
        self.bot: Raspbot | None = None if args.no_remote else Raspbot()
        self.driver: RaspbotDriver | None = None if args.dry_run else RaspbotDriver()
        self.drive_process: subprocess.Popen | None = None
        self.last_command_id: int | None = None
        self.last_command_poll = 0.0
        self.last_key_read = 0.0
        self.command_timeout = max(1.0, float(os.getenv("ONPLANT_COMMAND_TIMEOUT", "5.0")))
        self.running = True

    def start(self) -> None:
        if self.bot is not None:
            self.bot.Ctrl_IR_Switch(1)
        self.last_command_id = self.get_latest_command_id()
        print("OnPlant robot main started")
        print(f"server={self.server} robot_id={self.robot_id}")
        print(f"dry_run={self.args.dry_run} no_remote={self.args.no_remote}")
        if self.args.dry_run:
            print("DRY RUN: drive commands are logged only. Motors will not run.")
        else:
            print("LIVE MODE: start_light_search can move the robot. Use only on the testbed.")
        if self.last_command_id is None:
            print("command baseline pending: existing commands will be ignored after first successful poll")
        else:
            print(f"ignored existing commands up to id={self.last_command_id}")
        if self.args.no_remote:
            print("Remote disabled by --no-remote")
        else:
            print("Remote: 1=start light search, 2=stop, 3=status, 0=shutdown")

    def close(self) -> None:
        self.running = False
        self.stop_drive("main-close")
        if self.driver is not None:
            try:
                self.driver.stop()
                time.sleep(0.1)
                self.driver.stop()
            except Exception as exc:
                print("motor stop failed:", exc)
        if self.bot is not None:
            try:
                self.bot.Ctrl_IR_Switch(0)
            except Exception:
                pass

    def request_json(self, path: str, payload: dict | None = None, timeout: float = 3.0):
        url = f"{self.server}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="GET" if payload is None else "POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def download_file(self, url: str, path: Path, timeout: float = 30.0) -> None:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            path.write_bytes(response.read())

    def get_latest_command_id(self) -> int | None:
        try:
            commands = self.request_json(f"/api/robots/{self.robot_id}/commands?limit=100")
        except Exception as exc:
            print("command init failed:", exc)
            return None
        return max((int(item.get("id", 0)) for item in commands), default=0)

    def post_move_log(self, state: str, action: str, message: str) -> None:
        try:
            self.request_json(
                f"/api/robots/{self.robot_id}/move-logs",
                {
                    "state": state,
                    "action": action,
                    "message": message,
                    "source": "robot_main",
                },
                timeout=1.5,
            )
        except Exception:
            pass

    def post_idle_lidar(self, source: str) -> None:
        try:
            self.request_json(
                f"/api/robots/{self.robot_id}/lidar",
                {
                    "points": [],
                    "state": "IDLE",
                    "action": "STOP",
                    "source": source,
                    "front_blocked": False,
                    "danger": False,
                    "emergency": False,
                    "front_points": 0,
                },
                timeout=1.5,
            )
        except Exception:
            pass

    def speaker_card(self) -> str | None:
        device = self.args.speaker_device
        if device.startswith("plughw:"):
            device = device.removeprefix("plughw:")
        if device.startswith("hw:"):
            device = device.removeprefix("hw:")
        card = device.split(",", 1)[0].strip()
        return card if card.isdigit() else None

    def apply_speaker_volume(self) -> None:
        try:
            summary = self.request_json(f"/api/robots/{self.robot_id}/summary", timeout=2.0)
            volume = int((summary.get("config") or {}).get("speaker_volume", 60))
        except Exception:
            volume = 60
        volume = max(0, min(100, volume))
        card = self.speaker_card()
        if not card:
            return
        try:
            subprocess.run(
                ["amixer", "-c", card, "sset", self.args.speaker_control, f"{volume}%"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def play_audio(self, path: Path) -> None:
        if path.suffix.lower() == ".wav":
            subprocess.run(["aplay", "-D", self.args.speaker_device, str(path)], check=True)
            return
        for player in ("mpg123", "ffplay", "cvlc"):
            try:
                if player == "ffplay":
                    subprocess.run([player, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)], check=True)
                elif player == "cvlc":
                    subprocess.run([player, "--play-and-exit", str(path)], check=True)
                else:
                    subprocess.run([player, "-q", str(path)], check=True)
                return
            except FileNotFoundError:
                continue
        raise RuntimeError("No MP3 player found. Install mpg123 on Raspberry Pi.")

    def speak(self, text: str, source: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        print("speak:", text[:80])
        try:
            result = self.request_json("/api/tts", {"text": text}, timeout=45.0)
            audio_url = str(result.get("audio_url") or "")
            if not audio_url:
                print("speak failed: no audio_url")
                return
            full_url = urllib.parse.urljoin(self.server + "/", audio_url.lstrip("/"))
            suffix = Path(audio_url.split("?", 1)[0]).suffix.lower()
            suffix = suffix if suffix in {".mp3", ".wav"} else ".mp3"
            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path = Path(temp_dir) / f"reply{suffix}"
                self.download_file(full_url, audio_path)
                self.apply_speaker_volume()
                self.play_audio(audio_path)
            self.post_move_log("MAIN", "SPEAK", f"source={source}")
        except Exception as exc:
            print("speak failed:", exc)

    def send_display_status(self) -> None:
        try:
            result = self.request_json(f"/api/robots/{self.robot_id}/remote", {"key": "3"})
            print("display status:", result.get("screen"))
            self.post_move_log("MAIN", "SHOW_STATUS", "display report requested")
        except Exception as exc:
            print("display status failed:", exc)

    def start_light_search(self, source: str) -> None:
        if self.drive_process and self.drive_process.poll() is None:
            print("light search already running")
            return
        if self.args.dry_run:
            print("DRY RUN: start_light_search ignored:", source)
            self.post_move_log("MAIN", "DRY_RUN_START_LIGHT_SEARCH", f"source={source}")
            return

        env = os.environ.copy()
        env["ONPLANT_SERVER_URL"] = self.server
        env["ONPLANT_ROBOT_ID"] = self.robot_id
        env.setdefault("ONPLANT_SENSOR_BUS", "3")
        env.setdefault("ONPLANT_BH1750_BUS", "3")
        env["ONPLANT_AUTO_START"] = "1"
        env["ONPLANT_DISABLE_IR"] = "1"
        env.setdefault("ONPLANT_DUMMY_LUX", "0")
        env.setdefault("ONPLANT_DUMMY_SOIL", "1")
        env.setdefault("ONPLANT_TARGET_LUX_MIN", "800")
        env.setdefault("ONPLANT_TARGET_LUX_MAX", "900")
        env.setdefault("ONPLANT_TARGET_LUX", "850")
        env.setdefault("ONPLANT_LIGHT_FOUND_MARGIN", "50")
        env.setdefault("ONPLANT_RETURN_STOP_MARGIN", "50")

        command = [sys.executable, str(self.project_dir / "lidar_fsm_drive.py")]
        print("start light search:", source)
        self.drive_process = subprocess.Popen(command, cwd=str(self.project_dir), env=env)
        self.post_move_log("MAIN", "START_LIGHT_SEARCH", f"source={source}")

    def stop_drive(self, source: str) -> None:
        if self.args.dry_run:
            print("DRY RUN: stop requested:", source)
            self.post_move_log("MAIN", "DRY_RUN_STOP", f"source={source}")
            return

        if self.drive_process and self.drive_process.poll() is None:
            print("stop drive process:", source)
            self.drive_process.terminate()
            try:
                self.drive_process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.drive_process.kill()
                self.drive_process.wait(timeout=2)
        self.drive_process = None

        if self.driver is not None:
            try:
                self.driver.stop()
                time.sleep(0.1)
                self.driver.stop()
                time.sleep(0.1)
                self.driver.stop()
            except Exception as exc:
                print("motor stop failed:", exc)

        self.post_move_log("MAIN", "STOP", f"source={source}")
        self.post_idle_lidar(source)

    def shutdown(self) -> None:
        self.stop_drive("shutdown")
        self.post_move_log("MAIN", "SHUTDOWN", "remote shutdown requested")
        if not self.args.enable_shutdown:
            print("shutdown requested, but --enable-shutdown is not set")
            return
        subprocess.Popen(["sudo", "shutdown", "now"])

    def handle_command(self, command: dict) -> None:
        command_id = int(command.get("id", 0))
        if command_id <= self.last_command_id:
            return
        self.last_command_id = command_id

        name = str(command.get("command", ""))
        print(f"server command id={command_id} command={name}")
        if name == "start_light_search":
            self.start_light_search(f"server-command-{command_id}")
        elif name == "stop":
            self.stop_drive(f"server-command-{command_id}")
        elif name == "show_status":
            self.send_display_status()
        elif name == "speak":
            self.speak(str(command.get("value") or ""), f"server-command-{command_id}")
        else:
            print("unknown command ignored:", name)

    def poll_commands(self, now: float) -> None:
        if now - self.last_command_poll < self.args.command_interval:
            return
        self.last_command_poll = now

        try:
            commands = self.request_json(
                f"/api/robots/{self.robot_id}/commands?limit=30",
                timeout=self.command_timeout,
            )
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            print("command poll failed:", exc)
            return

        if self.last_command_id is None:
            self.last_command_id = max((int(item.get("id", 0)) for item in commands), default=0)
            print(f"command baseline ready: ignored existing commands up to id={self.last_command_id}")
            return

        for command in commands:
            self.handle_command(command)

    def read_ir_key(self) -> int:
        if self.bot is None:
            return 0
        try:
            key = self.bot.read_data_array(0x0C, 1)[0]
            return 0 if key in IGNORE_KEYS else int(key)
        except Exception:
            return 0

    def poll_remote(self, now: float) -> None:
        if now - self.last_key_read < self.args.key_interval:
            return
        self.last_key_read = now

        key = self.read_ir_key()
        if key == 0:
            return

        print("remote key:", key)
        if key == self.args.key_start:
            self.start_light_search("remote-1")
        elif key == self.args.key_stop:
            self.stop_drive("remote-2")
        elif key == self.args.key_status:
            self.send_display_status()
        elif key == self.args.key_shutdown:
            self.shutdown()

    def reap_drive_process(self) -> None:
        if self.drive_process and self.drive_process.poll() is not None:
            print("drive process exited:", self.drive_process.returncode)
            self.drive_process = None
            self.post_move_log("MAIN", "STOP", "drive process exited")
            self.post_idle_lidar("drive-exit")

    def run(self) -> None:
        self.start()
        while self.running:
            now = time.monotonic()
            if not self.args.no_remote:
                self.poll_remote(now)
            self.poll_commands(now)
            self.reap_drive_process()
            time.sleep(0.05)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OnPlant robot main command and remote loop")
    parser.add_argument("--server", default=os.getenv("ONPLANT_SERVER", DEFAULT_SERVER_URL))
    parser.add_argument("--robot-id", default=os.getenv("ONPLANT_ROBOT_ID", DEFAULT_ROBOT_ID))
    parser.add_argument("--project-dir", default=os.getenv("ONPLANT_PROJECT_DIR", str(Path(__file__).resolve().parent)))
    parser.add_argument("--command-interval", type=float, default=1.0)
    parser.add_argument("--key-interval", type=float, default=0.2)
    parser.add_argument("--key-start", type=int, default=START_KEY)
    parser.add_argument("--key-stop", type=int, default=STOP_KEY)
    parser.add_argument("--key-status", type=int, default=STATUS_KEY)
    parser.add_argument("--key-shutdown", type=int, default=SHUTDOWN_KEY)
    parser.add_argument("--speaker-device", default=os.getenv("ONPLANT_SPEAKER_DEVICE", DEFAULT_SPEAKER_DEVICE))
    parser.add_argument("--speaker-control", default=os.getenv("ONPLANT_SPEAKER_CONTROL", "PCM"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-remote", action="store_true")
    parser.add_argument("--enable-shutdown", action="store_true")
    return parser.parse_args()


def main() -> int:
    app = RobotMain(parse_args())

    def stop_handler(_signum, _frame) -> None:
        app.running = False

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    try:
        app.run()
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
