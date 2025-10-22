from fastapi import FastAPI
from routes.home import router
from fastapi.staticfiles import StaticFiles

app = FastAPI()




app.include_router(router)