# file: download_router.py
import os
import tempfile
import shutil
import asyncio
from typing import Optional

import requests
from fastapi import APIRouter, Request, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, JSONResponse
from pytubefix import YouTube
import yt_dlp

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# helper to clean file after response
def remove_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print("Failed to remove temp file:", path, e)

def normalize_youtube_url(url: str) -> str:
    if "youtu.be/" in url:
        url = url.split("?")[0].replace("youtu.be/", "www.youtube.com/watch?v=")
    return url

def make_requests_session(proxy: Optional[str] = None) -> requests.Session:
    session = requests.Session()
    proxies = {}
    if proxy:
        proxies = {"http": proxy, "https": proxy}
    if proxies:
        session.proxies.update(proxies)
    return session

@router.get("/")
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@router.post("/download")
async def download(request: Request, background_tasks: BackgroundTasks, url: str = Form(...)):
    url = url.strip()
    if not url:
        return JSONResponse(status_code=400, content={"error": "No URL provided"})

    url = normalize_youtube_url(url)
    tmp_file = None

    # read optional proxy config
    proxy = os.getenv("PROXY") or os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")

    # Try pytubefix first with auto PO token
    try:
        session = make_requests_session(proxy)
        video = YouTube(url, session=session, use_po_token=True)  # auto-generate token
        stream = video.streams.get_highest_resolution()

        fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        tmp_file = tmp_path

        out_dir = os.path.dirname(tmp_file)
        filename = os.path.basename(tmp_file)
        stream.download(output_path=out_dir, filename=filename)

        background_tasks.add_task(remove_file, tmp_file)
        return FileResponse(tmp_file, media_type="video/mp4", filename="video.mp4")
    except Exception as e:
        err_str = str(e)
        print("pytubefix attempt failed:", err_str)

        # fallback to yt-dlp
        try:
            tmp_dir = tempfile.mkdtemp()
            out_template = os.path.join(tmp_dir, "video.%(ext)s")

            env = os.environ.copy()
            if proxy:
                env["HTTP_PROXY"] = proxy
                env["HTTPS_PROXY"] = proxy

            ydl_opts = {
                "format": "best[ext=mp4]/best",
                "outtmpl": out_template,
                "noplaylist": True,
                "nopart": True,
            }

            def run_ydl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                for fname in os.listdir(tmp_dir):
                    if fname.startswith("video."):
                        return os.path.join(tmp_dir, fname)
                items = os.listdir(tmp_dir)
                if items:
                    return os.path.join(tmp_dir, items[0])
                raise RuntimeError("yt-dlp did not produce an output file")

            file_path = await asyncio.to_thread(run_ydl)

            def cleanup_dir(path: str):
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                except Exception as e2:
                    print("Failed to cleanup tmp dir:", path, e2)

            background_tasks.add_task(cleanup_dir, tmp_dir)
            return FileResponse(file_path, media_type="video/mp4", filename="video.mp4")
        except Exception as e2:
            print("yt-dlp fallback failed:", str(e2))
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Both pytubefix and yt-dlp failed",
                    "pytubefix_error": err_str,
                    "ytdlp_error": str(e2),
                },
            )
