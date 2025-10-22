from fastapi import APIRouter, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, JSONResponse
import tempfile
import os
from pytubefix import YouTube

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/")
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@router.post("/download")
def download(request: Request, url: str = Form(...)):
    try:
        # Convert youtu.be links to youtube.com
        if "youtu.be/" in url:
            url = url.split("?")[0].replace("youtu.be/", "www.youtube.com/watch?v=")
            print(f"Normalized URL: {url}")

        video = YouTube(url)
        stream = video.streams.get_highest_resolution()

        # Use a temporary file (safe for serverless)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            file_path = stream.download(output_path=os.path.dirname(tmp.name),
                                        filename=os.path.basename(tmp.name))
            filename = os.path.basename(file_path)

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="video/mp4"
        )

    except Exception as err:
        print(f"Download error: {err}")
        return JSONResponse(status_code=400, content={"error": str(err)})
