import os
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from instagrapi import Client

app = FastAPI()
templates = Jinja2Templates(directory="templates")

class NakrutkaRequest(BaseModel):
    link: str  # Bu yerga Instagram username yoziladi
    count: int

def load_instagram_accounts():
    accounts = []
    if os.path.exists("accounts.txt"):
        with open("accounts.txt", "r") as f:
            for line in f:
                if ":" in line:
                    username, password = line.strip().split(":", 1)
                    accounts.append({"username": username, "password": password})
    return accounts

@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/start-nakrutka")
async def start_instagram_nakrutka(data: NakrutkaRequest):
    accounts = load_instagram_accounts()
    if not accounts:
        raise HTTPException(status_code=400, detail="accounts.txt faylida akkauntlar topilmadi!")
    
    success_count = 0
    limit = min(data.count, len(accounts))
    
    for acc in accounts:
        if success_count >= limit:
            break
            
        cl = Client()
        cl.set_user_agent("Mozilla/5.0 (Linux; Android 9; Redmi 9)")
        
        try:
            # Instagramga kirish
            cl.login(acc["username"], acc["password"])
            # Profil ID-sini olish va obuna bo'lish
            user_id = cl.user_id_from_username(data.link)
            cl.user_follow(user_id)
            
            success_count += 1
            # Blok tushmasligi uchun 15 soniya kutish
            await asyncio.sleep(15)
        except Exception as e:
            print(f"Xatolik [{acc['username']}]: {e}")
            continue
            
    return {"status": "completed", "joined": success_count}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
