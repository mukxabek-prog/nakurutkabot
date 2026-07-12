import os
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pyrogram import Client
from pyrogram.errors import FloodWait, UserDeactivated, AuthKeyUnregistered

app = FastAPI()

# HTML shablonlarni ulash
templates = Jinja2Templates(directory="templates")

SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

# API uchun kiruvchi ma'lumotlar modeli
class NakrutkaRequest(BaseModel):
    link: str
    count: int

async def join_single_account(session_path, channel_link):
    """Bitta akkauntni kanalga qo'shish logikasi"""
    session_name = os.path.splitext(os.path.basename(session_path))[0]
    api_id = 6
    api_hash = "eb06d4abfb49dc3eeb1aeb98ae0f581e"
    
    try:
        async with Client(session_name, api_id=api_id, api_hash=api_hash, workdir=SESSIONS_DIR) as client_app:
            await client_app.join_chat(channel_link)
            return True
    except Exception as e:
        print(f"Xatolik [{session_name}]: {e}")
        return False

# 1. Bosh sahifa (HTML ko'rsatish)
@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# 2. Nakrutka boshlash API nuqtasi
@app.post("/api/start-nakrutka")
async def start_nakrutka_api(data: NakrutkaRequest):
    all_sessions = [
        os.path.join(SESSIONS_DIR, f) 
        for f in os.listdir(SESSIONS_DIR) 
        if f.endswith('.session')
    ]
    
    if not all_sessions:
        raise HTTPException(status_code=400, detail="Serverda faol akkauntlar (.session fayllari) mavjud emas!")
    
    joined_success = 0
    limit = min(data.count, len(all_sessions)) # So'ralgan miqdor yoki boricha akkaunt
    
    for session_path in all_sessions:
        if joined_success >= limit:
            break
            
        result = await join_single_account(session_path, data.link)
        if result:
            joined_success += 1
            
        # Akkauntlar srazu blok bo'lmasligi uchun 3 soniya kutish
        await asyncio.sleep(3)
        
    return {"status": "completed", "joined": joined_success}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
