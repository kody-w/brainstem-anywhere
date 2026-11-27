"""The one build step (rapp-static-api/1.1). Input: manifest.json. Output: everything else.

    python3 build.py

Fetches the grail (the unchanged Brainstem kernel) and brainfreeze, each pinned by commit, freezes the stock
Brainstem and packs it as one self-waking file. Same pins in, same files out: when the pins have not changed,
nothing is rebuilt and nothing is rewritten. Published files under versions/ are never changed or removed.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def fetch(repo, commit, dest):
    if not (dest / ".git").is_dir():
        subprocess.run(["git", "init", "-q", str(dest)], check=True)
        subprocess.run(["git", "-C", str(dest), "remote", "add", "origin", repo], check=True)
    subprocess.run(["git", "-C", str(dest), "fetch", "-q", "--depth", "1", "origin", commit], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "-q", "--force", commit], check=True)
    got = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if got != commit:
        sys.exit(f"pin mismatch for {repo}: wanted {commit}, got {got}")


def write_if_changed(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def main():
    m = json.loads((HERE / "manifest.json").read_text())
    pins = {"grail": m["grail"]["commit"], "brainfreeze": m["brainfreeze"]["commit"]}
    input_sha = sha256(json.dumps(pins, sort_keys=True).encode())
    reg_path = HERE / "registry.json"
    old = json.loads(reg_path.read_text()) if reg_path.exists() else {}
    current = next((e for e in old.get("entries", []) if e.get("input_sha256") == input_sha), None)

    if current and (HERE / current["path"]).is_file():
        entry = current                                   # same pins: keep the published file as is
    else:
        grail, bf = CACHE / "grail", CACHE / "brainfreeze"
        fetch(m["grail"]["repo"], pins["grail"], grail)
        fetch(m["brainfreeze"]["repo"], pins["brainfreeze"], bf)
        with tempfile.TemporaryDirectory() as t:
            src = Path(t) / "rapp_brainstem"
            shutil.copytree(grail / m["grail"]["folder"], src,
                            ignore=shutil.ignore_patterns("__pycache__", ".brainstem_data", ".env", "tests"))
            env = {**os.environ, "PYTHONPATH": str(bf)}
            snap, run = Path(t) / "default.snapshot.tar.gz", Path(t) / "brainstem.py"
            subprocess.run([sys.executable, "-m", "brainfreeze", "freeze", str(src), "--out", str(snap)],
                           check=True, env=env, stdout=subprocess.DEVNULL)
            subprocess.run([sys.executable, "-m", "brainfreeze", "pack", str(snap), "--out", str(run)],
                           check=True, env=env, stdout=subprocess.DEVNULL)
            blob = run.read_bytes()
        digest = sha256(blob)
        rel = f"versions/brainstem/{digest[:12]}.py"
        if not (HERE / rel).exists():                     # append-only
            (HERE / rel).parent.mkdir(parents=True, exist_ok=True)
            (HERE / rel).write_bytes(blob)
        version = (grail / m["grail"]["folder"] / "VERSION").read_text().strip()
        agents = sorted(p.stem for p in (grail / m["grail"]["folder"] / "agents").glob("*_agent.py")
                        if p.name != "basic_agent.py")
        entry = {"name": "brainstem", "path": rel, "sha256": digest, "sha8": digest[:12], "size": len(blob),
                 "brainstem_version": version, "agents": agents, "grail_commit": pins["grail"],
                 "brainfreeze_commit": pins["brainfreeze"], "input_sha256": input_sha,
                 "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    entries = [entry] + [e for e in old.get("entries", []) if e.get("sha256") != entry["sha256"]]
    generated = old.get("generated") if old.get("entries", [None])[0] == entry else entry["built_at"]
    base = m["pages_base"]
    latest = {"schema": "brainstem-anywhere-brainstem/1.0", "generated_at": generated,
              "source": m["grail"]["repo"] + "/tree/" + pins["grail"],
              "download": f"{base}/{entry['path']}", "raw": f"{m['raw_base']}/{entry['path']}",
              "file_name": "brainstem.py", "sha256": entry["sha256"], "size": entry["size"],
              "brainstem_version": entry["brainstem_version"], "agents": entry["agents"],
              "say_to_your_ai": m["sentence"]}
    registry = {"schema": "brainstem-anywhere-registry/1.0", "generated": generated,
                "pages_base": base, "raw_base": m["raw_base"],
                "summary": {"latest": entry["sha8"], "versions": len(entries),
                            "brainstem_version": entry["brainstem_version"]},
                "entries": entries}
    status = {"schema": "brainstem-anywhere-status/1.0", "generated_at": generated, "ok": True,
              "latest": entry["sha8"], "brainstem_version": entry["brainstem_version"]}
    badge = {"schemaVersion": 1, "label": "brainstem", "message": entry["brainstem_version"], "color": "blue"}
    dump = lambda o: json.dumps(o, indent=2) + "\n"
    write_if_changed(reg_path, dump(registry))
    write_if_changed(HERE / "api/v1/brainstem.json", dump(latest))
    write_if_changed(HERE / "api/v1/status.json", dump(status))
    write_if_changed(HERE / "api/v1/badge.json", dump(badge))
    write_if_changed(HERE / "llms.txt", f"""# Brainstem anywhere

> One file that wakes a RAPP Brainstem (your own AI as files: soul, agents, memory) inside any AI that can run
> Python, such as claude.ai. The AI becomes its model; the Brainstem's agents run in the AI's sandbox.

## Use it
1. Download the file: {latest['download']} (sha256 {entry['sha256']})
2. Attach it in your AI and say: "{m['sentence']}"
3. When done, the AI hands back ONE file (`host take-home brainstem-home.py`): this Brainstem now, memory and chat.
   At home: `python3 brainstem-home.py`. (Or with a chat.json: `python3 brainstem.py --home chat.json`.) Import
   continues the chat in the page.

## API
- {base}/api/v1/brainstem.json  (schema brainstem-anywhere-brainstem/1.0): latest file, hash, agents, sentence
- {base}/registry.json  (schema brainstem-anywhere-registry/1.0): every version, append-only under versions/
- {base}/api/v1/status.json

## Made from
- Brainstem kernel (unchanged): {m['grail']['repo']} @ {pins['grail']}
- Packer: {m['brainfreeze']['repo']} @ {pins['brainfreeze']}
""")
    print(f"brainstem {entry['brainstem_version']} -> {entry['path']} ({entry['size']} bytes)")


if __name__ == "__main__":
    main()
