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
        # keep silent; cleanup best-effort
        print("Failed to remove temp file:", path, e)

def normalize_youtube_url(url: str) -> str:
    if "youtu.be/" in url:
        # remove query part then convert
        url = url.split("?")[0].replace("youtu.be/", "www.youtube.com/watch?v=")
    return url

def make_requests_session(proxy: Optional[str] = None) -> requests.Session:
    session = requests.Session()
    proxies = {}
    if proxy:
        proxies = {"http": proxy, "https": proxy}
    else:
        # allow HTTP(S)_PROXY or global env proxies to be used implicitly by requests
        pass
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

    # read env config
    po_token = os.getenv("PO_TOKEN")  # optional PoToken for pytubefix
    proxy = os.getenv("PROXY") or os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")

    # Try pytubefix first (less likely to be blocked if PoToken provided)
    try:
        session = make_requests_session(proxy)
        # pytubefix accepts a requests.Session object and a use_po_token argument
        yt_kwargs = {}
        if po_token:
            yt_kwargs["use_po_token"] = po_token

        # pass session to YouTube constructor if supported
        video = YouTube(url, session=session, **yt_kwargs)
        stream = video.streams.get_highest_resolution()

        # create a temp file path and download into it
        fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)  # close the low-level fd; yt downloader will write by path
        tmp_file = tmp_path

        # pytubefix stream.download usually supports output_path and filename
        # we download directly to the temp path's directory with filename as basename
        out_dir = os.path.dirname(tmp_file)
        filename = os.path.basename(tmp_file)
        # some implementations of stream.download return the file path; we keep our tmp_file path
        stream.download(output_path=out_dir, filename=filename)
        # final path is tmp_file
        background_tasks.add_task(remove_file, tmp_file)
        return FileResponse(tmp_file, media_type="video/mp4", filename="video.mp4")
    except Exception as e:
        err_str = str(e)
        print("pytubefix attempt failed:", err_str)

        # If the error contains bot-detection or similar, fall back to yt-dlp
        # (we fall back on any exception here to maximize success rate)
        try:
            # prepare a temp dir for yt-dlp to write into
            tmp_dir = tempfile.mkdtemp()
            # build a safe output template
            out_template = os.path.join(tmp_dir, "video.%(ext)s")

            # If a proxy is set, forward it to yt-dlp via environment variables for subprocess/network
            env = os.environ.copy()
            if proxy:
                env["HTTP_PROXY"] = proxy
                env["HTTPS_PROXY"] = proxy

            ydl_opts = {
                "format": "best[ext=mp4]/best",  # prefer mp4
                "outtmpl": out_template,
                "noplaylist": True,
                "nopart": True,  # do not keep .part file
                # quiet false so we can catch info. The library will raise on errors anyway.
            }

            # run yt-dlp (synchronously inside thread) — use asyncio.to_thread for non-blocking
            def run_ydl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                # find the resulting file (video.*) in tmp_dir
                for fname in os.listdir(tmp_dir):
                    if fname.startswith("video."):
                        return os.path.join(tmp_dir, fname)
                # fallback: any file
                items = os.listdir(tmp_dir)
                if items:
                    return os.path.join(tmp_dir, items[0])
                raise RuntimeError("yt-dlp did not produce an output file")

            file_path = await asyncio.to_thread(run_ydl)

            # schedule cleanup of temp dir after response
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
            # final fallback: return both errors
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Both pytubefix and yt-dlp failed",
                    "pytubefix_error": err_str,
                    "ytdlp_error": str(e2),
                },
            )
