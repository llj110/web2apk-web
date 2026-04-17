import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="Web2Apk")

BUILDS_DIR = Path(os.environ.get("BUILD_DIR", "/tmp/builds"))
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/tmp/web2apk_workspace"))
TOOLS_DIR = Path(os.environ.get("TOOLS_DIR", str(WORKSPACE_DIR)))
WEB2APK_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "web2apk.py")
WEB2APK_SCRIPT = os.path.abspath(WEB2APK_SCRIPT)

# Global lock: only one APK build runs at a time
build_lock = threading.Lock()


class BuildRequest(BaseModel):
    url: str = Field(..., min_length=1)
    name: str = Field(default="WebApp", min_length=1)
    package: str = Field(default="com.example.webapp", min_length=1)


def _write_status(
    job_id: str,
    status: str,
    message: str = "",
    log: str = "",
    download_url: str = "",
) -> None:
    status_path = BUILDS_DIR / job_id / "status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "job_id": job_id,
                "status": status,
                "message": message,
                "log": log,
                "download_url": download_url,
                "updated_at": time.time(),
            },
            f,
            ensure_ascii=False,
        )


def _read_status(job_id: str) -> dict:
    status_path = BUILDS_DIR / job_id / "status.json"
    if not status_path.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    with open(status_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _run_build(job_id: str, req: BuildRequest) -> None:
    job_dir = BUILDS_DIR / job_id
    workspace = WORKSPACE_DIR / job_id
    log_path = job_dir / "build.log"

    _write_status(job_id, "pending", "正在排队等待构建资源…")

    build_lock.acquire()
    try:
        _write_status(job_id, "running", "正在构建 APK，请稍候…")

        # Symlink pre-installed tools into the per-job workspace
        for tool_name in ["jdk", "android-sdk", "gradle-7.5"]:
            src = TOOLS_DIR / tool_name
            dst = workspace / tool_name
            if not dst.exists() and src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(src, dst)

        cmd = [
            "python3",
            WEB2APK_SCRIPT,
            "--url",
            req.url,
            "--name",
            req.name,
            "--package",
            req.package,
            "--workspace",
            str(workspace),
            "--output",
            str(job_dir),
        ]

        env = os.environ.copy()
        env["WEB2APK_NO_DOWNLOAD"] = "1"

        with open(log_path, "w", encoding="utf-8") as log_f:
            result = subprocess.run(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )

        log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""

        # Locate generated APK
        safe_name = req.name.replace(" ", "_")
        apk_candidates = list(job_dir.glob(f"{safe_name}-debug.apk"))
        if not apk_candidates:
            apk_candidates = list(job_dir.glob("*.apk"))

        if result.returncode == 0 and apk_candidates:
            apk_path = apk_candidates[0]
            final_path = job_dir / f"{job_id}.apk"
            shutil.move(str(apk_path), str(final_path))
            _write_status(
                job_id,
                "success",
                message="构建成功！",
                download_url=f"/api/download/{job_id}",
            )
        else:
            tail = log_text[-4000:] if len(log_text) > 4000 else log_text
            _write_status(
                job_id,
                "failed",
                message="构建失败，请检查日志或参数是否正确",
                log=tail,
            )
    finally:
        build_lock.release()
        # Clean up temporary workspace to save disk
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)


def _cleanup_old_builds() -> None:
    while True:
        time.sleep(3600)  # check every hour
        cutoff = time.time() - 86400  # 24 hours
        for job_dir in BUILDS_DIR.iterdir():
            if not job_dir.is_dir():
                continue
            status_file = job_dir / "status.json"
            if not status_file.exists():
                continue
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
                if data.get("updated_at", 0) < cutoff:
                    shutil.rmtree(job_dir, ignore_errors=True)
            except Exception:
                pass


@app.on_event("startup")
def _startup() -> None:
    BUILDS_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_cleanup_old_builds, daemon=True).start()


@app.post("/api/build")
def create_build(req: BuildRequest, background_tasks: BackgroundTasks) -> dict:
    job_id = str(uuid.uuid4())[:8]
    background_tasks.add_task(_run_build, job_id, req)
    return {"job_id": job_id, "status": "pending"}


@app.get("/api/status/{job_id}")
def get_status(job_id: str) -> dict:
    return _read_status(job_id)


@app.get("/api/download/{job_id}")
def download_apk(job_id: str) -> FileResponse:
    status = _read_status(job_id)
    if status.get("status") != "success":
        raise HTTPException(status_code=400, detail="Build not ready or failed")
    apk_path = BUILDS_DIR / job_id / f"{job_id}.apk"
    if not apk_path.exists():
        raise HTTPException(status_code=404, detail="APK file not found")
    return FileResponse(
        apk_path,
        media_type="application/vnd.android.package-archive",
        filename=f"{job_id}.apk",
    )


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
