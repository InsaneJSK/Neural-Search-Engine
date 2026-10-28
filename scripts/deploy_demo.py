"""Update the linked Vercel project after starting demo_host.py. Never prints secrets."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    npx = shutil.which("npx")
    if not npx:
        raise SystemExit("Install Node.js first.")
    if not (ROOT / "frontend/.vercel/project.json").exists():
        raise SystemExit("First run npx vercel login and npx vercel link inside frontend/.")
    state = json.loads((ROOT / ".demo/host.json").read_text())
    config = dotenv_values(ROOT / ".env.demo")
    values = {key: config[key] for key in ("NSE_API_TOKEN",)}
    values.update(NSE_BACKEND_URL=state["url"])
    command = [npx, "--yes", "vercel@65.5.0"]
    for name, value in values.items():
        result = subprocess.run(command + ["env", "add", name, "--environment", "production", "--force", "--yes",
                                          "--sensitive" if name == "NSE_API_TOKEN" else "--no-sensitive"],
                                input=value, text=True, cwd=ROOT / "frontend", capture_output=True)
        if result.returncode:
            # Do not print command output, which could include the supplied secret.
            raise SystemExit(f"Vercel could not save {name}. Check login/project permissions.")
        print(f"Configured {name}", flush=True)
    result = subprocess.run(command + ["deploy", "--prod", "--yes"], cwd=ROOT / "frontend")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
