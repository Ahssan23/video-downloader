from fastapi import APIRouter, Request,Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os 
from pytubefix import YouTube



router = APIRouter()


templates= Jinja2Templates(directory="templates")
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


@router.get("/")
def home(request:Request):
    return templates.TemplateResponse("index.html",{"request":request})


@router.post("/download")
def download(request:Request, url: str= Form(...)):
    DOWNLOAD_DIR = "downloads"

    if "youtu.be/" in url:
        url = url.split("?")[0].replace("youtu.be/", "www.youtube.com/watch?v=")
        print(url)
    video = YouTube(url)
    stream  = video.streams.get_highest_resolution()
    try:
    
        file_path = stream.download(output_path=DOWNLOAD_DIR)
        filename = os.path.basename(file_path)

        
        return FileResponse(
            path=file_path ,
            filename=filename,
            media_type="video/mp4"
        )
    except Exception as err:
        print(err)
    
