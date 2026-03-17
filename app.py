import json
import subprocess
import sys
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
SETTINGS_TEMPLATE_PATH = APP_DIR / "repo_clone.template.json"
CLONES_DIR = APP_DIR / "cloned_repos"


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class CloneOnlyApp:
    def __init__(self) -> None:
        self.config_store = ConfigStore(CONFIG_PATH)
        self.config = self.config_store.load()

        self.root = tk.Tk()
        self.root.title("GitHub Clone Helper")
        self.root.geometry("980x640")
        self.root.minsize(900, 580)
        self.root.configure(bg="#f3efe6")

        self.repo_url = self.config.get("repo_url", "")
        self.clone_path = self.config.get("clone_path", "")

        self.status_var = tk.StringVar(value="설정 JSON을 불러오고 `저장소 받기`를 누르세요.")
        self.path_var = tk.StringVar(value=self.clone_path)

        self.log_text = None

        self._build_ui()
        self.ensure_settings_template()
        self._log("App ready.")

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg="#173a2d", padx=18, pady=14)
        header.pack(fill="x", padx=14, pady=(14, 10))
        tk.Label(
            header,
            text="GitHub Clone Helper",
            bg="#173a2d",
            fg="#f8f4ee",
            font=("Helvetica", 24, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="GitHub 저장소 URL 하나만 받아서 로컬에 clone 하는 단순 앱입니다.",
            bg="#173a2d",
            fg="#d7e5dc",
            font=("Helvetica", 12),
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        controls = tk.Frame(self.root, bg="#f3efe6")
        controls.pack(fill="x", padx=14, pady=(0, 10))

        tk.Button(
            controls,
            text="템플릿 생성",
            command=self.create_template_copy,
            bg="#e5e7eb",
            fg="#111827",
            relief="flat",
            padx=18,
            pady=10,
        ).pack(side="right")
        tk.Button(
            controls,
            text="설정 JSON 불러오기",
            command=self.load_settings_file,
            bg="#e5e7eb",
            fg="#111827",
            relief="flat",
            padx=18,
            pady=10,
        ).pack(side="right", padx=(0, 8))
        tk.Button(
            controls,
            text="저장소 받기",
            command=self.clone_repo,
            bg="#1f7a57",
            fg="white",
            relief="flat",
            padx=18,
            pady=10,
        ).pack(side="right", padx=(0, 8))

        info = tk.Frame(self.root, bg="#eef3ef", bd=1, relief="solid", padx=18, pady=12)
        info.pack(fill="x", padx=14, pady=(0, 10))
        tk.Label(info, text="마지막 설정된 URL", bg="#eef3ef", fg="#334155", font=("Helvetica", 10, "bold")).pack(anchor="w")
        tk.Label(info, text=self.repo_url or "(없음)", bg="#eef3ef", fg="#0f172a", font=("Menlo", 10), justify="left", wraplength=940).pack(anchor="w", pady=(4, 8))
        tk.Label(info, text="로컬 저장 경로", bg="#eef3ef", fg="#334155", font=("Helvetica", 10, "bold")).pack(anchor="w")
        tk.Label(info, textvariable=self.path_var, bg="#eef3ef", fg="#0f172a", font=("Menlo", 10), justify="left", wraplength=940).pack(anchor="w", pady=(4, 8))
        tk.Label(info, textvariable=self.status_var, bg="#eef3ef", fg="#0f172a", font=("Helvetica", 11), justify="left", wraplength=940).pack(anchor="w")

        body = tk.Frame(self.root, bg="#fffaf2", bd=1, relief="solid", padx=18, pady=16)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.log_text = tk.Text(body, font=("Menlo", 11), bg="#0f172a", fg="#e2e8f0", insertbackground="#e2e8f0", relief="solid", bd=1, wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def ensure_settings_template(self) -> None:
        template = {
            "repo_url": "https://github.com/your-name/your-repo.git"
        }
        SETTINGS_TEMPLATE_PATH.write_text(json.dumps(template, indent=2), encoding="utf-8")

    def create_template_copy(self) -> None:
        destination = filedialog.asksaveasfilename(
            title="설정 템플릿 저장",
            defaultextension=".json",
            initialfile="repo_clone.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(APP_DIR),
        )
        if not destination:
            return
        Path(destination).write_text(SETTINGS_TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        self.status_var.set(f"설정 템플릿 생성 완료: {destination}")
        self._log(f"Created template: {destination}")

    def load_settings_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="설정 JSON 선택",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(APP_DIR),
        )
        if not file_path:
            return

        try:
            settings = json.loads(Path(file_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("설정 읽기 실패", str(exc))
            return

        repo_url = str(settings.get("repo_url", "")).strip()
        if not repo_url:
            messagebox.showerror("설정 오류", "`repo_url` 값이 비어 있습니다.")
            return

        self.repo_url = repo_url
        self.config["repo_url"] = repo_url
        self.config_store.save(self.config)
        self.status_var.set(f"설정 로드 완료. 이제 `저장소 받기`를 누르세요.\nURL: {repo_url}")
        self._log(f"Loaded settings: {file_path}")

    def clone_repo(self) -> None:
        if not self.repo_url:
            messagebox.showwarning("URL 필요", "먼저 설정 JSON을 불러오세요.")
            return

        CLONES_DIR.mkdir(parents=True, exist_ok=True)
        repo_name = self.repo_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        destination = CLONES_DIR / repo_name

        if destination.exists():
            messagebox.showwarning("이미 존재", f"이미 같은 이름의 폴더가 있습니다.\n{destination}")
            self.path_var.set(str(destination))
            return

        self._log(f"Cloning {self.repo_url}")
        result = subprocess.run(
            ["git", "clone", self.repo_url, str(destination)],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self._log(result.stderr.strip())
            messagebox.showerror("clone 실패", result.stderr.strip() or "git clone 실패")
            return

        self.clone_path = str(destination)
        self.path_var.set(self.clone_path)
        self.config["clone_path"] = self.clone_path
        self.config_store.save(self.config)
        self._log(result.stdout.strip() or "Clone completed.")
        self.status_var.set(f"저장소를 로컬에 받았습니다.\n{destination}")
        messagebox.showinfo("완료", f"저장소를 받았습니다.\n{destination}")

    def _log(self, message: str) -> None:
        if not self.log_text:
            return
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    app = CloneOnlyApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
