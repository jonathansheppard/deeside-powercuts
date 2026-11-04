#!/opt/homebrew/bin/python3.11
"""Rebuilds data/powercuts.json and pushes it to GitHub Pages. Run from cron after powercuts.py.
GitHub Pages has a soft limit of 10 builds an hour, so this pushes only when the cuts or the record change,
plus a check-in every 30 minutes so the page can tell visitors when its data has gone stale."""
import datetime, json, os, subprocess, sys
from pathlib import Path

SITE = Path(__file__).resolve().parent
DATA = "data/powercuts.json"
CHECK_IN = datetime.timedelta(minutes=30)
os.environ.pop("GITHUB_TOKEN", None)  # use gh's stored login, as push_site_data.sh does


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(SITE), *args], capture_output=True, text=True)
    if check and r.returncode:
        log(f"git {args[0]} failed: " + (r.stderr or r.stdout).strip()[-400:])
        r.check_returncode()
    return r.stdout


def log(msg):
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M} {msg}")


def without_time(d):
    return {k: v for k, v in d.items() if k != "checked_at"}


def push():
    git("pull", "-q", "--rebase", "--autostash", "origin", "main")
    git("push", "-q", "origin", "main")


def main():
    subprocess.run([sys.executable, str(SITE / "build_data.py")], check=True)
    new = json.loads((SITE / DATA).read_text())
    old = json.loads(git("show", f"HEAD:{DATA}"))
    age = datetime.datetime.fromisoformat(new["checked_at"]) - datetime.datetime.fromisoformat(old["checked_at"])
    changed = without_time(new) != without_time(old)
    if changed or age >= CHECK_IN:
        git("add", DATA)
        git("-c", "user.name=Deeside data bot", "-c", "user.email=jonathan@deeside.com", "commit", "-qm",
            f"{'Power cut update' if changed else 'Check-in'} {datetime.datetime.now():%F %R}", "--", DATA)
        push()
        log("pushed: " + ("data changed" if changed else "check-in"))
    else:
        git("checkout", "-q", "--", DATA)  # only the time moved on, so leave the commit for later
        # A failed push leaves a commit waiting here, so try it again.
        if git("rev-list", "@{u}..HEAD").strip():
            push()
            log("pushed: retried earlier commit")


if __name__ == "__main__":
    main()
