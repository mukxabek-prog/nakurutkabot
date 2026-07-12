# login.py
from pyrogram import Client
import os

# Akkaunt nomini yozasiz (masalan raqamni o'zi)
name = input("Akkaunt nomini kiriting (masalan: +99890XXXXXXX): ")
api_id = 6
api_hash = "eb06d4abfb49dc3eeb1aeb98ae0f581e"

app = Client(name, api_id=api_id, api_hash=api_hash, workdir="sessions")

with app:
    print(f"✅ {name} muvaffaqiyatli saqlandi!")
