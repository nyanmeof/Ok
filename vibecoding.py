#!/usr/bin/env python3
"""
Discord Quest Auto-Completer (English & 3-Option Menu Version)
"""

import os
import sys
import re
import time
import json
import base64
import random
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import requests

# -- Default Configuration --
API_BASE = "https://discord.com/api/v9"
POLL_INTERVAL = 60          
HEARTBEAT_INTERVAL = 20     
AUTO_ACCEPT = True          
LOG_PROGRESS = True
DEBUG = False               

SUPPORTED_TASKS = {
    "WATCH_VIDEO",
    "PLAY_ON_DESKTOP",
    "STREAM_ON_DESKTOP",
    "PLAY_ACTIVITY",
    "WATCH_VIDEO_ON_MOBILE",
}


# -- Console Logging System (Deep Blue/Cyan Theme) --
class Logger:
    RESET  = "\033[0m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    
    BLUE   = "\033[34m"
    B_BLUE = "\033[1;34m" 
    CYAN   = "\033[96m"
    B_CYAN = "\033[1;96m"

    @classmethod
    def log(cls, msg: str, level: str = "info") -> None:
        if level == "debug" and not DEBUG:
            return
        if level == "progress" and not LOG_PROGRESS:
            return

        ts = datetime.now().strftime("%H:%M:%S")
        prefixes = {
            "info":     f"{cls.B_BLUE}[INFO]{cls.RESET}",
            "ok":       f"{cls.GREEN}[  OK]{cls.RESET}",
            "warn":     f"{cls.YELLOW}[WARN]{cls.RESET}",
            "error":    f"{cls.RED}[ ERR]{cls.RESET}",
            "progress": f"{cls.DIM}[PROG]{cls.RESET}",
            "debug":    f"{cls.DIM}[DBG ]{cls.RESET}",
        }
        prefix = prefixes.get(level, f"[{level.upper()}]")
        print(f"{cls.DIM}{ts}{cls.RESET} {prefix} {msg}")


# -- Quest Data Model --
class DiscordQuest:
    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.id: str = data.get("id", "")
        self.config: Dict[str, Any] = data.get("config", {})
        self.task_config: Dict[str, Any] = (
            self.config.get("taskConfig") or 
            self.config.get("task_config") or 
            self.config.get("taskConfigV2") or 
            self.config.get("task_config_v2") or {}
        )
        self.user_status: Dict[str, Any] = data.get("userStatus") or data.get("user_status") or {}

    @property
    def name(self) -> str:
        messages = self.config.get("messages", {})
        name = messages.get("questName") or messages.get("quest_name")
        if name: return name.strip()
        game = messages.get("gameTitle") or messages.get("game_title")
        if game: return game.strip()
        return self.config.get("application", {}).get("name") or f"Quest#{self.id}"

    @property
    def expires_at(self) -> Optional[str]:
        return self.config.get("expiresAt") or self.config.get("expires_at")

    @property
    def task_type(self) -> Optional[str]:
        tasks = self.task_config.get("tasks", {})
        for t in SUPPORTED_TASKS:
            if t in tasks: return t
        return None

    @property
    def is_completable(self) -> bool:
        if self.expires_at:
            try:
                exp_dt = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
                if exp_dt <= datetime.now(timezone.utc): return False
            except ValueError: pass
        return self.task_type is not None

    @property
    def is_enrolled(self) -> bool:
        return bool(self.user_status.get("enrolledAt") or self.user_status.get("enrolled_at"))

    @property
    def is_completed(self) -> bool:
        return bool(self.user_status.get("completedAt") or self.user_status.get("completed_at"))

    @property
    def seconds_needed(self) -> int:
        if not self.task_type: return 0
        return self.task_config.get("tasks", {}).get(self.task_type, {}).get("target", 0)

    @property
    def seconds_done(self) -> float:
        if not self.task_type: return 0.0
        progress = self.user_status.get("progress", {})
        return progress.get(self.task_type, {}).get("value", 0.0)

    @property
    def enrolled_at_timestamp(self) -> float:
        enrolled_str = self.user_status.get("enrolledAt") or self.user_status.get("enrolled_at")
        if enrolled_str:
            try: return datetime.fromisoformat(enrolled_str.replace("Z", "+00:00")).timestamp()
            except ValueError: pass
        return time.time()


# -- Discord Client Connection & Spoofing --
class DiscordClient:
    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.build_number = 504649 
        self.username = "Unknown"
        self.user_id = "0"

    def sync_build_number(self) -> None:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        try:
            r = self.session.get("https://discord.com/app", headers={"User-Agent": ua}, timeout=10)
            if r.status_code == 200:
                scripts = re.findall(r'/assets/([a-f0-9]+)\.js', r.text)
                for asset_hash in scripts[-5:]:
                    ar = self.session.get(f"https://discord.com/assets/{asset_hash}.js", headers={"User-Agent": ua}, timeout=5)
                    m = re.search(r'buildNumber["\s:]+["\s]*(\d{5,7})', ar.text)
                    if m:
                        self.build_number = int(m.group(1))
                        break
        except Exception:
            pass
        self._setup_headers()

    def _setup_headers(self) -> None:
        sp_obj = {
            "os": "Windows", "browser": "Discord Client", "release_channel": "stable",
            "client_version": "1.0.9175", "os_version": "10.0.26100", "os_arch": "x64",
            "app_arch": "x64", "system_locale": "en-US",
            "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
            "browser_version": "32.2.7", "client_build_number": self.build_number,
            "native_build_number": 59498, "client_event_source": None,
        }
        sp_base64 = base64.b64encode(json.dumps(sp_obj).encode()).decode()
        
        self.session.headers.update({
            "Authorization": self.token,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "User-Agent": sp_obj["browser_user_agent"],
            "X-Super-Properties": sp_base64,
            "X-Discord-Locale": "en-US",
            "X-Discord-Timezone": "Asia/Ho_Chi_Minh",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
        })

    def request(self, method: str, path: str, payload: Optional[dict] = None) -> requests.Response:
        url = f"{API_BASE}{path}"
        response = self.session.request(method, url, json=payload, timeout=15)
        return response

    def validate_token(self) -> bool:
        self._setup_headers()
        try:
            r = self.request("GET", "/users/@me")
            if r.status_code == 200:
                user = r.json()
                self.username = user.get("username", "Unknown")
                self.user_id = user.get("id", "0")
                return True
            return False
        except Exception:
            return False


# -- Core Automation Engine --
class QuestAutocompleter:
    def __init__(self, client: DiscordClient):
        self.client = client
        self.completed_ids = set()

    def fetch_quests(self) -> List[DiscordQuest]:
        try:
            r = self.client.request("GET", "/quests/@me")
            if r.status_code == 429:
                retry_after = r.json().get("retry_after", 10)
                time.sleep(retry_after + 1)
                return self.fetch_quests()
            if r.status_code == 200:
                data = r.json()
                raw_quests = data.get("quests", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                return [DiscordQuest(q) for q in raw_quests]
            return []
        except Exception:
            return []

    def enroll_quest(self, quest: DiscordQuest) -> bool:
        try:
            r = self.client.request("POST", f"/quests/{quest.id}/enroll", {
                "location": 11, "is_targeted": False, "metadata_raw": None, "metadata_sealed": None,
                "traffic_metadata_raw": quest.data.get("traffic_metadata_raw"),
                "traffic_metadata_sealed": quest.data.get("traffic_metadata_sealed"),
            })
            if r.status_code in (200, 201, 204):
                Logger.log(f"Successfully enrolled in quest: {Logger.BOLD}{quest.name}{Logger.RESET}", "ok")
                return True
        except Exception: pass
        return False

    def process_video_quest(self, quest: DiscordQuest) -> None:
        Logger.log(f"Running Video: {Logger.BOLD}{quest.name}{Logger.RESET} ({quest.seconds_done:.0f}/{quest.seconds_needed}s)", "info")
        seconds_done = quest.seconds_done
        
        while seconds_done < quest.seconds_needed:
            max_allowed = (time.time() - quest.enrolled_at_timestamp) + 10
            if max_allowed - seconds_done >= 7:
                timestamp = min(quest.seconds_needed, seconds_done + 7 + random.random())
                try:
                    r = self.client.request("POST", f"/quests/{quest.id}/video-progress", {"timestamp": timestamp})
                    if r.status_code == 200:
                        seconds_done = timestamp
                        Logger.log(f"  [{quest.name}] Progress: {seconds_done:.0f}/{quest.seconds_needed}s", "progress")
                        if r.json().get("completed_at"): break
                    elif r.status_code == 429:
                        time.sleep(r.json().get("retry_after", 5) + 1)
                except Exception: pass
            time.sleep(1)
            
        self.client.request("POST", f"/quests/{quest.id}/video-progress", {"timestamp": quest.seconds_needed})
        Logger.log(f"Completed Video: {Logger.BOLD}{quest.name}{Logger.RESET}", "ok")

    def process_heartbeat_quest(self, quest: DiscordQuest) -> None:
        remaining_min = max(0, (quest.seconds_needed - quest.seconds_done) // 60)
        Logger.log(f"Simulating {quest.task_type}: {Logger.BOLD}{quest.name}{Logger.RESET} (~{remaining_min} min remaining)", "info")
        
        pid = random.randint(1000, 30000)
        stream_key = f"call:0:{pid}" if "ACTIVITY" not in quest.task_type else "call:0:1"
        seconds_done = quest.seconds_done

        while seconds_done < quest.seconds_needed:
            try:
                r = self.client.request("POST", f"/quests/{quest.id}/heartbeat", {"stream_key": stream_key, "terminal": False})
                if r.status_code == 200:
                    body = r.json()
                    progress_data = body.get("progress", {})
                    if quest.task_type in progress_data:
                        seconds_done = progress_data[quest.task_type].get("value", seconds_done)
                    
                    Logger.log(f"  [{quest.name}] Progress: {seconds_done:.0f}/{quest.seconds_needed}s", "progress")
                    if body.get("completed_at") or seconds_done >= quest.seconds_needed: break
                elif r.status_code == 429:
                    time.sleep(r.json().get("retry_after", 10) + 1)
                    continue
            except Exception: pass
            time.sleep(HEARTBEAT_INTERVAL)

        self.client.request("POST", f"/quests/{quest.id}/heartbeat", {"stream_key": stream_key, "terminal": True})
        Logger.log(f"Completed Challenge: {Logger.BOLD}{quest.name}{Logger.RESET}", "ok")

    def start_loop(self) -> None:
        print(f"\n{Logger.B_BLUE}┌──────────────────────────────────────────────────────────┐")
        print(f"│ {Logger.BOLD}ENGINE RUNNING (DASHBOARD){Logger.RESET}{Logger.B_BLUE}                              │")
        print(f"├──────────────────────────────────────────────────────────┤")
        print(f"│ User Account: {Logger.RESET}{self.client.username:<43} {Logger.B_BLUE}│")
        print(f"│ Auto-Accept : {Logger.RESET}{('ENABLED' if AUTO_ACCEPT else 'DISABLED'):<43} {Logger.B_BLUE}│")
        print(f"│ Debug Mode  : {Logger.RESET}{('ENABLED' if DEBUG else 'DISABLED'):<43} {Logger.B_BLUE}│")
        print(f"│ Scan Cycle  : {Logger.RESET}{f'Every {POLL_INTERVAL} seconds':<43} {Logger.B_BLUE}│")
        print(f"└──────────────────────────────────────────────────────────┘{Logger.RESET}\n")

        cycle = 0
        while True:
            cycle += 1
            Logger.log(f"── Scan Cycle #{cycle} Initiated ──", "info")
            quests = self.fetch_quests()

            if not quests:
                Logger.log("No quests available at the moment.", "info")
            else:
                for q in quests:
                    status = f"{Logger.GREEN}[CMP]{Logger.RESET}" if q.is_completed else (f"{Logger.YELLOW}[ACT]{Logger.RESET}" if q.is_enrolled else f"{Logger.DIM}[LOCKED]{Logger.RESET}")
                    Logger.log(f"  {status} {q.name} [{q.task_type or 'Unsupported'}]", "info")

                if AUTO_ACCEPT:
                    unaccepted = [q for q in quests if not q.is_enrolled and not q.is_completed and q.is_completable]
                    if unaccepted:
                        Logger.log(f"Found {len(unaccepted)} new quest(s), enrolling automatically...", "info")
                        for q in unaccepted:
                            self.enroll_quest(q)
                            time.sleep(2)
                        quests = self.fetch_quests()

                actionable = [q for q in quests if q.is_enrolled and not q.is_completed and q.is_completable and q.id not in self.completed_ids]
                
                if actionable:
                    for q in actionable:
                        Logger.log(f"--- Processing: {Logger.BOLD}{q.name}{Logger.RESET} ({q.task_type}) ---", "info")
                        if "VIDEO" in q.task_type: self.process_video_quest(q)
                        else: self.process_heartbeat_quest(q)
                        self.completed_ids.add(q.id)
                else:
                    Logger.log("All current quests are fully processed.", "info")

            Logger.log(f"Sleeping for {POLL_INTERVAL}s before next cycle... (Ctrl+C to Exit)\n", "info")
            time.sleep(POLL_INTERVAL)


# -- Main Interactive Menu Interface --
def show_interactive_menu() -> None:
    global AUTO_ACCEPT, DEBUG, POLL_INTERVAL
    
    token = ""
    client = None

    # Try loading a saved token at initial startup
    if os.path.exists(".token"):
        with open(".token", "r", encoding="utf-8") as f:
            token = f.read().strip()

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"""
{Logger.BOLD}{Logger.B_BLUE}╔══════════════════════════════════════════════════════════╗
║               vibe coding                        ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝{Logger.RESET}""")
        
        # Display Current Active Session Status
        print(f"\n{Logger.BOLD}CURRENT SESSION STATUS:{Logger.RESET}")
        if client and client.username != "Unknown":
            print(f"  Account: {Logger.GREEN}{client.username}{Logger.RESET} (ID: {client.user_id})")
        else:
            if token:
                print(f"  Account: {Logger.YELLOW}Token loaded but not verified yet.{Logger.RESET}")
            else:
                print(f"  Account: {Logger.RED}No token logged in. Please use Option 2.{Logger.RESET}")

        print(f"\n{Logger.BOLD}MAIN MENU OPTIONS:{Logger.RESET}")
        print(f"  [{Logger.B_BLUE}1{Logger.RESET}] Start Engine")
        print(f"  [{Logger.B_BLUE}2{Logger.RESET}] Log Token (Login / Change Account)")
        print(f"  [{Logger.B_BLUE}3{Logger.RESET}] Modify Modes & Settings")
        print(f"  [{Logger.RED}0{Logger.RESET}] Exit Program")
        
        choice = input(f"\nSelect an option ({Logger.BOLD}0-3{Logger.RESET}): ").strip()
        
        # OPTION 1: START SYSTEM
        if choice == '1':
            if not token:
                print(f"{Logger.RED}[ERR] No token configuration found. Please use Option 2 first!{Logger.RESET}")
                time.sleep(2)
                continue
            
            if not client:
                client = DiscordClient(token)
                
            print(f"\n{Logger.B_BLUE}[*] Validating session token with Discord API...{Logger.RESET}")
            if client.validate_token():
                print(f"{Logger.GREEN}[✓] Authorization successful as {client.username}.{Logger.RESET}")
                print(f"{Logger.B_BLUE}[*] Synchronizing stable Discord client build number...{Logger.RESET}")
                client.sync_build_number()
                with open(".token", "w", encoding="utf-8") as f:
                    f.write(token)
                
                # Launch automated task loop
                completer = QuestAutocompleter(client)
                try:
                    completer.start_loop()
                except KeyboardInterrupt:
                    print()
                    Logger.log("Application terminated safely by user request.", "info")
                    sys.exit(0)
            else:
                print(f"{Logger.RED}[ERR] Saved token is invalid or expired. Unable to start!{Logger.RESET}")
                token = ""
                client = None
                time.sleep(2.5)

        # OPTION 2: LOG NEW TOKEN (Loop dynamic verification, no crash on failure)
        elif choice == '2':
            while True:
                new_token = input(f"\n{Logger.BOLD} Paste/Enter Discord Token: {Logger.RESET}").strip()
                if not new_token:
                    print(f"{Logger.RED}[ERR] Token field cannot be blank!{Logger.RESET}")
                    break
                
                print(f"{Logger.B_BLUE}[*] Verifying new credentials...{Logger.RESET}")
                test_client = DiscordClient(new_token)
                if test_client.validate_token():
                    token = new_token
                    client = test_client
                    print(f"{Logger.GREEN}[✓] Success! Authenticated as {client.username}.{Logger.RESET}")
                    with open(".token", "w", encoding="utf-8") as f:
                        f.write(token)
                    time.sleep(2)
                    break
                else:
                    print(f"{Logger.RED}[ERR] Invalid Discord Token provided!{Logger.RESET}")
                    retry = input(f"Would you like to try entering it again? (y/{Logger.BOLD}N{Logger.RESET}): ").strip().lower()
                    if retry not in ('y', 'yes'):
                        break

        # OPTION 3: MODIFY CONFIG MODES
        elif choice == '3':
            while True:
                os.system('cls' if os.name == 'nt' else 'clear')
                print(f"{Logger.BOLD}{Logger.B_BLUE}🛠️  CONFIGURATION CONTROL PANEL:{Logger.RESET}")
                print(f"  [{Logger.B_BLUE}1{Logger.RESET}] Auto-Enroll New Quests : {Logger.GREEN if AUTO_ACCEPT else Logger.RED}{'ENABLED' if AUTO_ACCEPT else 'DISABLED'}{Logger.RESET}")
                print(f"  [{Logger.B_BLUE}2{Logger.RESET}] Deep Debug Mode        : {Logger.GREEN if DEBUG else Logger.RED}{'ENABLED' if DEBUG else 'DISABLED'}{Logger.RESET}")
                print(f"  [{Logger.B_BLUE}3{Logger.RESET}] Scan Interval Sequence : {Logger.YELLOW}{POLL_INTERVAL} seconds{Logger.RESET}")
                print(f"  [{Logger.B_BLUE}4{Logger.RESET}] Return to Main Menu")
                
                sub_choice = input(f"\nSelect parameter to edit (1-4): ").strip()
                if sub_choice == '1':
                    AUTO_ACCEPT = not AUTO_ACCEPT
                elif sub_choice == '2':
                    DEBUG = not DEBUG
                elif sub_choice == '3':
                    try:
                        val = int(input(f"Enter custom frequency in seconds (Recommended > 30s): ").strip())
                        if val >= 5: 
                            POLL_INTERVAL = val
                        else:
                            print(f"{Logger.RED}[ERR] Warning: Excessively fast scan speed might activate security flags!{Logger.RESET}")
                            time.sleep(2)
                    except ValueError:
                        print(f"{Logger.RED}[ERR] Input type invalid. Digits only.{Logger.RESET}")
                        time.sleep(1.5)
                elif sub_choice == '4':
                    break

        # OPTION 0: SAFE EXIT
        elif choice == '0':
            print(f"\n{Logger.YELLOW}Closing engine session securely. Goodbye!{Logger.RESET}")
            sys.exit(0)


if __name__ == "__main__":
    show_interactive_menu()
