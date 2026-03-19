import json
import os
import socketserver
import subprocess
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "web"
CLONES_DIR = APP_DIR / "cloned_repos"
SSH_DIR = Path.home() / ".ssh"
SSH_PRIVATE_KEY = SSH_DIR / "id_ed25519"
SSH_PUBLIC_KEY = SSH_DIR / "id_ed25519.pub"
ASKPASS_PATH = APP_DIR / "git_askpass_web.py"
DEFAULT_PORT = 8765
MAX_PORT_TRIES = 20


def load_asset(name: str) -> bytes:
    return (STATIC_DIR / name).read_bytes()


def repo_name_from_url(repo_url: str) -> str:
    repo_name = repo_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    return repo_name


def list_cloned_repos() -> list[dict]:
    if not CLONES_DIR.exists():
        return []
    repos = []
    for child in sorted(CLONES_DIR.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        repos.append({"name": child.name, "path": str(child)})
    return repos


def ssh_status() -> dict:
    public_key = SSH_PUBLIC_KEY.read_text(encoding="utf-8").strip() if SSH_PUBLIC_KEY.exists() else ""
    test = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-T", "git@github.com"],
        capture_output=True,
        text=True,
    )
    output = (test.stdout + "\n" + test.stderr).strip()
    authenticated = "successfully authenticated" in output.lower()
    return {
        "has_key": SSH_PUBLIC_KEY.exists(),
        "public_key": public_key,
        "authenticated": authenticated,
        "test_output": output,
    }


def ensure_askpass_script() -> None:
    ASKPASS_PATH.write_text(
        "import os\n"
        "import sys\n"
        "prompt = ' '.join(sys.argv[1:]).lower()\n"
        "if 'username' in prompt:\n"
        "    sys.stdout.write(os.environ.get('AUTOGIT_USERNAME', ''))\n"
        "else:\n"
        "    sys.stdout.write(os.environ.get('AUTOGIT_PASSWORD', ''))\n",
        encoding="utf-8",
    )


def git_env(username: str = "", password: str = "") -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Auto-accept GitHub's host key on first SSH connect, but still reject changed keys.
    env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=accept-new"
    if username and password:
        env["GIT_ASKPASS"] = str(ASKPASS_PATH)
        env["AUTOGIT_USERNAME"] = username
        env["AUTOGIT_PASSWORD"] = password
    return env


class CloneHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(load_asset("index.html"))
            return

        if parsed.path == "/app.js":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.end_headers()
            self.wfile.write(load_asset("app.js"))
            return

        if parsed.path == "/styles.css":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.end_headers()
            self.wfile.write(load_asset("styles.css"))
            return

        if parsed.path == "/status":
            self._send_json(
                {
                    "clone_dir": str(CLONES_DIR),
                    "repos": list_cloned_repos(),
                    "ssh": ssh_status(),
                }
            )
            return

        if parsed.path == "/open-github-ssh":
            webbrowser.open("https://github.com/settings/keys")
            self._send_json({"ok": True})
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/clone", "/push", "/generate-ssh-key"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8")
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            payload = json.loads(raw_body or "{}")
        else:
            payload = {key: values[0] for key, values in parse_qs(raw_body).items()}

        if parsed.path == "/clone":
            self.handle_clone(payload)
            return
        if parsed.path == "/push":
            self.handle_push(payload)
            return
        if parsed.path == "/generate-ssh-key":
            self.handle_generate_ssh_key()
            return

    def log_message(self, format: str, *args) -> None:
        return

    def handle_clone(self, payload: dict) -> None:
        repo_url = str(payload.get("repo_url", "")).strip()
        if not repo_url:
            self._send_json({"ok": False, "error": "repo_url is required"}, status=HTTPStatus.BAD_REQUEST)
            return

        repo_name = repo_name_from_url(repo_url)
        if not repo_name:
            self._send_json({"ok": False, "error": "invalid repository URL"}, status=HTTPStatus.BAD_REQUEST)
            return

        CLONES_DIR.mkdir(parents=True, exist_ok=True)
        destination = CLONES_DIR / repo_name
        if destination.exists():
            self._send_json(
                {
                    "ok": False,
                    "error": f"destination already exists: {destination}",
                    "destination": str(destination),
                },
                status=HTTPStatus.CONFLICT,
            )
            return

        result = subprocess.run(
            ["git", "clone", repo_url, str(destination)],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            env=git_env(
                str(payload.get("username", "")).strip(),
                str(payload.get("password", "")).strip(),
            ),
        )
        if result.returncode != 0:
            self._send_json(
                {
                    "ok": False,
                    "error": result.stderr.strip() or "git clone failed",
                    "stdout": result.stdout.strip(),
                },
                status=HTTPStatus.BAD_GATEWAY,
            )
            return

        self._send_json(
            {
                "ok": True,
                "destination": str(destination),
                "stdout": result.stdout.strip(),
            }
        )
        subprocess.run(["open", str(destination)], check=False)

    def handle_push(self, payload: dict) -> None:
        repo_name = str(payload.get("repo_name", "")).strip()
        commit_message = str(payload.get("commit_message", "Update from GitHub Clone Helper")).strip()
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", "")).strip()
        if not repo_name:
            self._send_json({"ok": False, "error": "repo_name is required"}, status=HTTPStatus.BAD_REQUEST)
            return

        repo_path = CLONES_DIR / repo_name
        if not repo_path.exists() or not (repo_path / ".git").exists():
            self._send_json({"ok": False, "error": f"repo not found: {repo_name}"}, status=HTTPStatus.NOT_FOUND)
            return

        steps = [
            ["git", "add", "-A"],
            ["git", "commit", "-m", commit_message],
            ["git", "push"],
        ]
        outputs = []
        for cmd in steps:
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                env=git_env(username, password),
            )
            if result.returncode != 0:
                # `git commit` with no changes should not be treated as fatal.
                stderr = result.stderr.strip()
                stdout = result.stdout.strip()
                if cmd[1] == "commit" and ("nothing to commit" in stdout.lower() or "nothing to commit" in stderr.lower()):
                    outputs.append(stdout or stderr)
                    self._send_json(
                        {
                            "ok": True,
                            "message": "변경 사항이 없어 push를 건너뒀습니다.",
                            "output": "\n\n".join(filter(None, outputs)),
                        }
                    )
                    return
                self._send_json(
                    {
                        "ok": False,
                        "error": stderr or stdout or "git command failed",
                        "output": "\n\n".join(filter(None, outputs + [stdout, stderr])),
                    },
                    status=HTTPStatus.BAD_GATEWAY,
                )
                return
            outputs.append(result.stdout.strip() or result.stderr.strip())

        self._send_json(
            {
                "ok": True,
                "message": "push 완료",
                "output": "\n\n".join(filter(None, outputs)),
            }
        )

    def handle_generate_ssh_key(self) -> None:
        SSH_DIR.mkdir(parents=True, exist_ok=True)
        if SSH_PUBLIC_KEY.exists():
            self._send_json({"ok": True, "message": "existing key", "ssh": ssh_status()})
            return

        result = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-C", "autogit-local", "-f", str(SSH_PRIVATE_KEY), "-N", ""],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self._send_json(
                {"ok": False, "error": result.stderr.strip() or "ssh-keygen failed"},
                status=HTTPStatus.BAD_GATEWAY,
            )
            return

        self._send_json({"ok": True, "message": "ssh key created", "ssh": ssh_status()})

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    if not STATIC_DIR.exists():
        print(f"Missing static directory: {STATIC_DIR}", file=sys.stderr)
        return 1
    ensure_askpass_script()

    httpd = None
    port = DEFAULT_PORT
    for candidate in range(DEFAULT_PORT, DEFAULT_PORT + MAX_PORT_TRIES):
        try:
            httpd = socketserver.TCPServer(("127.0.0.1", candidate), CloneHandler)
            port = candidate
            break
        except OSError:
            continue

    if httpd is None:
        print("Could not find an available local port.", file=sys.stderr)
        return 1

    url = f"http://127.0.0.1:{port}"
    with httpd:
        print(f"GitHub Clone Helper running at {url}")
        print(f"Clones will be stored in: {CLONES_DIR}")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
