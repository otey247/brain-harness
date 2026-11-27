"""Test a trusted kit as an offline consumer. Run with the Python used to build it."""

import argparse
import json
import os
import subprocess
import venv
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


def verify(archive: Path) -> None:
    if not __debug__:
        raise RuntimeError("verification requires Python assertions")
    with TemporaryDirectory(prefix="cited-consumer-") as tmp:
        home = Path(tmp)
        with ZipFile(archive) as source:
            source.extractall(home)
        kit = home / archive.stem
        manifest = json.loads((kit / "manifest.json").read_text())
        env_dir = home / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        scripts = env_dir / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("cited-search.exe" if os.name == "nt" else "cited-search")

        # Record even a caught network attempt. The asyncio loop uses local socket pairs.
        (home / "sitecustomize.py").write_text(
            "import os, sys\n"
            "def guard(event, args):\n"
            # pip's vendored urllib3 probes IPv6 availability by binding ::1 port 0 on import.
            "    if event == 'socket.bind' and args[1] == ('::1', 0):\n"
            "        raise OSError('loopback probe disabled')\n"
            "    if event in {'socket.connect', 'socket.bind', 'socket.getaddrinfo', 'socket.sendto'}:\n"
            "        open(os.environ['NETWORK_ATTEMPTS'], 'a').write(event + '\\n')\n"
            "        raise RuntimeError('network disabled during install verification')\n"
            "sys.addaudithook(guard)\n"
        )
        attempts = home / "network-attempts"
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TMP", "TEMP") if key in os.environ}
        env.update(
            HOME=str(home),
            USERPROFILE=str(home),
            PYTHONPATH=str(home),
            PYTHONNOUSERSITE="1",
            PATH=str(scripts),
            NETWORK_ATTEMPTS=str(attempts),
            PIP_CONFIG_FILE=os.devnull,
            PIP_NO_INDEX="1",
            PIP_DISABLE_PIP_VERSION_CHECK="1",
        )

        # No project paths, provider keys or rg on PATH. Exercise the Python search fallback.
        def run(*args: str | Path, expected: int = 0) -> str:
            p = subprocess.run(args, cwd=home, env=env, capture_output=True, text=True, timeout=180)
            if p.returncode != expected:
                raise RuntimeError(f"{args} exited {p.returncode}, expected {expected}\n{p.stdout}\n{p.stderr}")
            return p.stdout

        run(
            python,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--no-index",
            "--only-binary=:all:",
            "--find-links",
            kit / "wheels",
            "--require-hashes",
            "-r",
            kit / "requirements.txt",
        )
        run(python, "-m", "pip", "check")
        assert json.loads(run(cli, "manifest")) == manifest
        schema = json.loads(run(cli, "schema"))
        assert schema["title"] == "Answer"
        # Ambient source-workspace settings must never enable a live model or change the smoke corpus.
        env.update(BRAIN_MODEL="openai:unused", BRAIN_BUNDLE=str(home / "missing"))
        logs = home / "logs"
        answer = json.loads(run(cli, "smoke", "--log-dir", logs))
        assert set(answer) == set(schema["properties"])
        assert not answer["abstained"] and answer["gaps"] == []
        (citation,) = answer["citations"]
        record = json.loads(next(logs.glob("*.jsonl")).read_text())
        assert record["opened"] == ["handoff.md"] and record["grep_hits"] == ["handoff.md"]
        assert record["answer"] == answer and record["citation_validity"] == 1.0
        assert citation["path"] == "handoff.md" and "18:30 UTC" in citation["quote"]
        run(cli, "ask", "question", expected=2)
        run(cli, "ask", "--live", "--allow-provider", "anthropic", "question", expected=1)
        run(cli, "ask", "--live", "--allow-provider", "openai", "question", expected=1)
        assert not attempts.exists(), attempts.read_text() if attempts.exists() else ""
        print(f"{archive.name}: clean wheel installation, pip check, manifest, schema and offline smoke passed")
        print(f"{citation['path']}:{citation['start_line']}-{citation['end_line']}  {citation['quote']}")
        print(f"Verified citation fraction {record['citation_validity']}; tool calls {record['usage']['tool_calls']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path)
    verify(parser.parse_args().zip.resolve())
