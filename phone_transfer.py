"""
Phone to Phone Transfer: copies data from one Android phone to another over USB (adb).

What it copies: photos and videos, downloads, documents / music / recordings, WhatsApp media, contacts (as a .vcf
file), apps (the programs themselves, without their data). A copy can stay on the computer in the "backup" folder
next to the program. Nothing is deleted on either phone.

Run: run.bat (or python phone_transfer.py). "USB debugging" must be enabled on both phones.
Interface languages: locales/*.json (one file per language, en.json is the reference).
"""
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
import zipfile
from pathlib import Path
from tkinter import messagebox, ttk

FROZEN = getattr(sys, "frozen", False)
HERE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent     # writable: backup, log
RES = Path(getattr(sys, "_MEIPASS", HERE)) if FROZEN else HERE                                  # read-only: locales
EXE = ".exe" if os.name == "nt" else ""
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PLATFORM_TOOLS = "https://dl.google.com/android/repository/platform-tools-latest-{os}.zip"

# option key (see locales) -> folders in the phone's internal storage
GROUPS = [
    ("g_photos", ["DCIM", "Pictures", "Movies"]),
    ("g_downloads", ["Download"]),
    ("g_docs", ["Documents", "Music", "Recordings", "Sounds", "Telegram", "Notifications", "Ringtones", "Alarms"]),
    ("g_whatsapp", ["Android/media/com.whatsapp"]),
]
# apps that are not installed on another phone (the manufacturer's own system programs)
SKIP_APPS = ("com.huawei.", "com.hicloud.", "com.hihonor.", "com.samsung.", "com.sec.", "com.android.", "com.gbox.",
             "com.miui.", "com.xiaomi.", "com.coloros.", "com.oplus.", "com.oneplus.", "com.vivo.", "com.motorola.")


# ------------------------------------------------------------------------------------------------------- languages
def load_languages():
    langs = {}
    for f in sorted((RES / "locales").glob("*.json")):
        try:
            langs[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return langs


def system_language():
    code = ""
    if os.name == "nt":
        try:
            import ctypes
            code = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
        except Exception:  # noqa: BLE001
            code = ""
    code = code or os.environ.get("LANG", "") or (locale.getlocale()[0] or "")
    return code[:2].lower()


LANGS = load_languages()
SETTINGS = HERE / "settings.json"


def read_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


LANG = read_settings().get("lang") or system_language()
if LANG not in LANGS:
    LANG = "en"


def T(key, **kw):
    text = LANGS.get(LANG, {}).get(key) or LANGS.get("en", {}).get(key) or key
    return text.format(**kw) if kw else text


# ------------------------------------------------------------------------------------------------------------- adb
def find_adb():
    places = [HERE / "platform-tools" / ("adb" + EXE), HERE / ("adb" + EXE)]
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            places.append(Path(os.environ[var]) / "platform-tools" / ("adb" + EXE))
    if os.environ.get("LOCALAPPDATA"):
        places.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk" / "platform-tools" / ("adb" + EXE))
    places.append(Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb")
    places.append(Path.home() / "Android" / "Sdk" / "platform-tools" / "adb")
    for p in places:
        if p.exists():
            return str(p)
    return shutil.which("adb")


def download_adb():
    """Google's platform-tools, from Google's own address, into the folder next to the program."""
    name = "windows" if os.name == "nt" else "darwin" if sys.platform == "darwin" else "linux"
    archive = HERE / "platform-tools.zip"
    urllib.request.urlretrieve(PLATFORM_TOOLS.format(os=name), archive)
    with zipfile.ZipFile(archive) as z:
        z.extractall(HERE)
    archive.unlink()
    tool = HERE / "platform-tools" / ("adb" + EXE)
    if os.name != "nt":
        tool.chmod(0o755)
    return str(tool)


ADB = find_adb()


def adb(serial, *args, timeout=None):
    r = subprocess.run([ADB, "-s", serial, *args], capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def shell(serial, command, timeout=None):
    return adb(serial, "shell", command, timeout=timeout)[1].replace("\r", "")


def storage(serial):
    """Used and free megabytes of the phone's internal storage."""
    df = shell(serial, "df -k /sdcard | tail -1").split()
    if len(df) >= 4 and df[2].isdigit() and df[3].isdigit():
        return int(df[2]) // 1024, int(df[3]) // 1024
    return 0, 0


def devices():
    """Connected phones. "used" is -1 for a phone that has not allowed USB debugging yet."""
    if not ADB:
        return []
    out = subprocess.run([ADB, "devices", "-l"], capture_output=True, creationflags=NO_WINDOW).stdout.decode("utf-8", "replace")
    found = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serial = parts[0]
            name = (shell(serial, "getprop ro.product.manufacturer").strip() + " " + shell(serial, "getprop ro.product.model").strip()).strip()
            found.append({"serial": serial, "name": name, "used": storage(serial)[0]})
        elif len(parts) >= 2 and parts[1] == "unauthorized":
            found.append({"serial": parts[0], "name": "", "used": -1})
    return found


class App:
    def __init__(self, root):
        self.root = root
        root.geometry("780x660")
        self.devs = []
        self.busy = False
        self.texts = []         # (widget, locale key): everything that is rewritten when the language changes

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        self.label(ttk.Label(top), "from").grid(row=0, column=0, sticky="w")
        self.src = ttk.Combobox(top, state="readonly", width=58)
        self.src.grid(row=0, column=1, padx=6, pady=3)
        self.label(ttk.Label(top), "to").grid(row=1, column=0, sticky="w")
        self.dst = ttk.Combobox(top, state="readonly", width=58)
        self.dst.grid(row=1, column=1, padx=6, pady=3)
        self.label(ttk.Button(top, command=self.refresh), "refresh").grid(row=0, column=2, padx=6)
        self.codes = sorted(LANGS, key=lambda c: LANGS[c].get("_name", c).lower())
        self.lang = ttk.Combobox(top, state="readonly", width=14, values=[LANGS[c].get("_name", c) for c in self.codes])
        self.lang.current(self.codes.index(LANG))
        self.lang.grid(row=1, column=2, padx=6)
        self.lang.bind("<<ComboboxSelected>>", self.set_language)

        box = self.label(ttk.LabelFrame(root, padding=10), "what")
        box.pack(fill="x", padx=10)
        self.vars = {}
        for i, (key, _) in enumerate(GROUPS):
            self.vars[key] = tk.BooleanVar(value=True)
            self.label(ttk.Checkbutton(box, variable=self.vars[key]), key).grid(row=i // 2, column=i % 2, sticky="w", padx=6, pady=2)
        self.contacts = tk.BooleanVar(value=True)
        self.apps = tk.BooleanVar(value=True)
        self.keep = tk.BooleanVar(value=True)
        self.label(ttk.Checkbutton(box, variable=self.contacts), "contacts").grid(row=2, column=0, sticky="w", padx=6, pady=2)
        self.label(ttk.Checkbutton(box, variable=self.apps), "apps").grid(row=2, column=1, sticky="w", padx=6, pady=2)
        self.label(ttk.Checkbutton(box, variable=self.keep), "keep").grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        bar = ttk.Frame(root, padding=10)
        bar.pack(fill="x")
        self.start = self.label(ttk.Button(bar, command=self.run), "start")
        self.start.pack(side="left")
        self.status = ttk.Label(bar, text="")
        self.status.pack(side="left", padx=12)
        self.progress = ttk.Progressbar(root, mode="determinate")
        self.progress.pack(fill="x", padx=10)

        self.log = tk.Text(root, height=20, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=10, pady=10)
        self.retranslate()
        root.after(100, self.first_run)

    # ------------------------------------------------------------------------------------------------- interface
    def label(self, widget, key):
        self.texts.append((widget, key))
        return widget

    def retranslate(self):
        self.root.title(T("title"))
        for widget, key in self.texts:
            widget.configure(text=T(key))
        self.show_devices()

    def set_language(self, _event=None):
        global LANG
        LANG = self.codes[self.lang.current()]
        try:
            SETTINGS.write_text(json.dumps({"lang": LANG}), encoding="utf-8")
        except OSError:
            pass
        self.retranslate()

    def say(self, text):
        def do():
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, do)
        try:
            with open(HERE / "transfer_log.txt", "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass

    def set_status(self, text, value=None):
        def do():
            self.status.configure(text=text)
            if value is not None:
                self.progress.configure(value=value)
        self.root.after(0, do)

    def first_run(self):
        """Without adb nothing works: offer to fetch it from Google."""
        global ADB
        if not ADB:
            if not messagebox.askyesno(T("title"), T("adb_ask")):
                self.say(T("adb_manual"))
                return
            self.say(T("adb_downloading"))
            self.root.update()
            try:
                ADB = download_adb()
                self.say(T("adb_ready"))
            except Exception as e:  # noqa: BLE001
                ADB = None
                self.say(T("adb_failed", e=e))
                self.say(T("adb_manual"))
                return
        self.refresh()

    def show_devices(self):
        a, b = self.src.current(), self.dst.current()
        labels = []
        for d in self.devs:
            if d["used"] < 0:
                labels.append(f"[{d['serial']}]  {T('unauthorized')}")
            else:
                labels.append(f"{d['name']}  [{d['serial']}]  {T('used', gb=f'{d['used'] / 1024:.1f}')}")
        self.src.configure(values=labels)
        self.dst.configure(values=labels)
        for box, i in ((self.src, a), (self.dst, b)):
            if 0 <= i < len(labels):
                box.current(i)
            else:
                box.set("")

    def refresh(self):
        if self.busy:
            return
        if not ADB:
            self.say(T("adb_manual"))
            return
        self.devs = devices()
        self.src.set("")
        self.dst.set("")
        self.show_devices()
        ready = [i for i, d in enumerate(self.devs) if d["used"] >= 0]
        if len(ready) >= 2:
            order = sorted(ready, key=lambda i: -self.devs[i]["used"])
            self.src.current(order[0])          # from: the phone that holds more data
            self.dst.current(order[1])
            self.say(T("found", n=len(ready), src=self.devs[order[0]]["name"], dst=self.devs[order[1]]["name"]))
        else:
            self.say(T("need_two"))

    def run(self):
        if self.busy:
            return
        a, b = self.src.current(), self.dst.current()
        if a < 0 or b < 0 or a == b or self.devs[a]["used"] < 0 or self.devs[b]["used"] < 0:
            messagebox.showwarning(T("title"), T("pick_two"))
            return
        s, d = self.devs[a], self.devs[b]
        if not messagebox.askyesno(T("title"), T("confirm", src=s["name"], dst=d["name"])):
            return
        self.busy = True
        self.start.configure(state="disabled")
        threading.Thread(target=self.work, args=(s, d), daemon=True).start()

    # ------------------------------------------------------------------------------------------------------ work
    def work(self, s, d):
        try:
            backup = HERE / "backup" / re.sub(r"[^\w.-]+", "_", s["name"])
            backup.mkdir(parents=True, exist_ok=True)
            steps = [(k, f) for k, f in GROUPS if self.vars[k].get()]
            total = len(steps) + int(self.contacts.get()) + int(self.apps.get())
            done = 0
            self.say(T("begin", src=s["name"], dst=d["name"]))
            sizes = self.measure(s, d, [f for _, folders in steps for f in folders])
            if sizes is None:
                self.set_status(T("st_error"))
                return
            if self.contacts.get():
                self.set_status(T("st_contacts"), 100 * done / max(total, 1))
                self.copy_contacts(s, d, backup)
                done += 1
            for key, folders in steps:
                self.set_status(T(key) + "…", 100 * done / max(total, 1))
                for folder in folders:
                    if folder in sizes:
                        self.copy_folder(s, d, folder, backup, sizes[folder])
                done += 1
            if self.apps.get():
                self.set_status(T("st_apps"), 100 * done / max(total, 1))
                self.copy_apps(s, d, backup)
                done += 1
            # The new phone's gallery does not notice files written over USB by itself (seen on Android 16):
            # ask the phone to look through its storage again.
            self.set_status(T("st_scan"))
            shell(d["serial"], "content call --uri content://media --method scan_volume --arg external_primary", timeout=900)
            self.say(T("scan_done"))
            if not self.keep.get():
                shutil.rmtree(backup, ignore_errors=True)
                self.say(T("backup_removed"))
            else:
                self.say(T("backup_kept", path=backup))
            self.set_status(T("done"), 100)
            self.say(T("done_log"))
        except Exception as e:  # noqa: BLE001
            self.say(T("error", e=e))
            self.set_status(T("st_error"))
        finally:
            self.busy = False
            self.root.after(0, lambda: self.start.configure(state="normal"))

    def measure(self, s, d, folders):
        """Megabytes of every folder that exists on the old phone; None when there is no room for them."""
        sizes = {}
        for folder in folders:
            if "exists" not in shell(s["serial"], f'[ -d "/sdcard/{folder}" ] && echo exists'):
                continue
            size = shell(s["serial"], f'du -sk "/sdcard/{folder}" | cut -f1').strip()
            sizes[folder] = int(size) // 1024 if size.isdigit() else 0
        need = sum(sizes.values())
        phone_free = storage(d["serial"])[1]
        if phone_free and need > phone_free:
            self.say(T("no_room_phone", need=need, free=phone_free))
            return None
        # with no copy kept, every folder leaves the computer as soon as it is on the new phone
        pc_need = need if self.keep.get() else max(sizes.values(), default=0)
        pc_free = shutil.disk_usage(HERE).free // (1024 * 1024)
        if pc_need > pc_free:
            self.say(T("no_room_pc", need=pc_need, free=pc_free))
            return None
        return sizes

    def copy_folder(self, s, d, folder, backup, mb):
        local = backup / "files" / folder
        local.parent.mkdir(parents=True, exist_ok=True)
        self.say(T("reading", folder=folder, mb=mb))
        code, out, err = adb(s["serial"], "pull", "-a", f"/sdcard/{folder}", str(local))
        tail = (out + err).strip().splitlines()[-1:] or [""]
        if code != 0:
            self.say(T("read_partial", msg=tail[0]))
        if not local.exists():
            return
        self.say(T("writing", folder=folder))
        parent = "/sdcard/" + "/".join(folder.split("/")[:-1])
        shell(d["serial"], f'mkdir -p "{parent}"')
        code, out, err = adb(d["serial"], "push", str(local), parent.rstrip("/") + "/")
        tail = (out + err).strip().splitlines()[-1:] or [""]
        self.say(T("write_ok" if code == 0 else "write_fail", msg=tail[0]))
        if not self.keep.get():
            shutil.rmtree(local, ignore_errors=True)

    def copy_contacts(self, s, d, backup):
        out = shell(s["serial"], "content query --uri content://com.android.contacts/data --projection raw_contact_id:mimetype:data1")
        people = {}
        for line in out.splitlines():
            m = re.match(r"Row: \d+ raw_contact_id=(\d+), mimetype=vnd\.android\.cursor\.item/(name|phone_v2|email_v2), data1=(.*)$", line)
            if not m or m.group(3) in ("", "NULL"):
                continue
            p = people.setdefault(m.group(1), {"name": "", "phones": [], "emails": []})
            if m.group(2) == "name":
                p["name"] = m.group(3).strip()
            elif m.group(2) == "phone_v2":
                p["phones"].append(m.group(3).strip())
            else:
                p["emails"].append(m.group(3).strip())
        cards, seen = [], set()
        for p in people.values():
            phones = list(dict.fromkeys(re.sub(r"[^\d+*#]", "", x) for x in p["phones"]))
            if not phones and not p["emails"]:
                continue
            key = (p["name"], tuple(phones), tuple(p["emails"]))
            if key in seen:                       # the same person again from WhatsApp / Telegram
                continue
            seen.add(key)
            name = p["name"] or (phones[0] if phones else p["emails"][0])
            esc = name.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            card = ["BEGIN:VCARD", "VERSION:3.0", f"N:{esc};;;;", f"FN:{esc}"]
            card += [f"TEL;TYPE=CELL:{x}" for x in phones]
            card += [f"EMAIL:{x}" for x in p["emails"]]
            card.append("END:VCARD")
            cards.append("\r\n".join(card))
        if not cards:
            self.say(T("no_contacts"))
            return
        vcf = backup / "contacts.vcf"
        vcf.write_text("\r\n".join(cards) + "\r\n", encoding="utf-8")
        adb(d["serial"], "push", str(vcf), "/sdcard/Download/contacts.vcf")
        shell(d["serial"], "am start -a android.intent.action.VIEW -d file:///sdcard/Download/contacts.vcf -t text/x-vcard")
        self.say(T("contacts_done", n=len(cards)))

    def copy_apps(self, s, d, backup):
        have = set(x.replace("package:", "").strip() for x in shell(d["serial"], "pm list packages").splitlines())
        apps = [x.replace("package:", "").strip() for x in shell(s["serial"], "pm list packages -3").splitlines() if x.strip()]
        apps = [a for a in apps if not a.startswith(SKIP_APPS)]
        todo = [a for a in apps if a not in have]
        self.say(T("apps_count", all=len(apps), have=len(apps) - len(todo), todo=len(todo)))
        ok, failed, blocked = 0, [], False
        for i, pkg in enumerate(todo, 1):
            self.set_status(T("st_app", i=i, n=len(todo), pkg=pkg))
            paths = [x.replace("package:", "").strip() for x in shell(s["serial"], f"pm path {pkg}").splitlines() if x.strip()]
            folder = backup / "apps" / pkg
            folder.mkdir(parents=True, exist_ok=True)
            files = []
            for k, p in enumerate(paths):
                f = folder / (f"{k}_{Path(p).name}")
                if adb(s["serial"], "pull", p, str(f))[0] == 0 and f.exists():
                    files.append(str(f))
            if not files:
                failed.append(pkg)
                self.say(T("app_fail", pkg=pkg, reason="pull"))
                continue
            args = ["install-multiple", "-r", *files] if len(files) > 1 else ["install", "-r", files[0]]
            try:
                code, out, err = adb(d["serial"], *args, timeout=600)
            except subprocess.TimeoutExpired:
                code, out, err = 1, "", "[TIMEOUT]"
            if code == 0 and "Success" in out + err:
                ok += 1
                self.say(f"  + {pkg}")
            else:
                failed.append(pkg)
                reason = (re.findall(r"\[([A-Z_0-9]+)", out + err) or ["?"])[0]
                blocked = blocked or "VERIFICATION" in reason
                self.say(T("app_fail", pkg=pkg, reason=reason))
            if not self.keep.get():
                shutil.rmtree(folder, ignore_errors=True)
        self.say(T("apps_done", ok=ok, failed=len(failed)))
        if failed:
            self.say(T("apps_failed_list", list=", ".join(failed)))
        if blocked:
            # the new phone's own check (Play Protect) refused them; this program does not switch that check off
            self.say(T("verify_hint"))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
