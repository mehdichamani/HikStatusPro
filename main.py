import asyncio
import os
import jdatetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from sqlmodel import Session, select, col
from database import init_db, get_session, Camera, Log, NVR, Settings, engine
from monitor import start_monitor_loop

class CsvContent(BaseModel):
    content: str

monitor_task = None

def seed_defaults():
    with Session(engine) as session:
        defaults = [
            ("MAIL_ENABLED", "false", "Enable Email Alerts"),
            ("MAIL_SERVER", "smtp.gmail.com", "SMTP Server"),
            ("MAIL_PORT", "587", "SMTP Port"),
            ("MAIL_USER", "email@gmail.com", "SMTP Username"),
            ("MAIL_PASS", "password", "SMTP Password"),
            ("MAIL_RECIPIENTS", "admin@example.com", "Recipients"),
            ("MAIL_FIRST_ALERT_DELAY_MINUTES", "1", "Delay before 1st alert"),
            ("MAIL_ALERT_FREQUENCY_MINUTES", "60", "Repeat every X mins"),
            ("TELEGRAM_ENABLED", "false", "Enable Telegram"),
            ("TELEGRAM_BOT_TOKEN", "", "Bot Token"),
            ("TELEGRAM_CHAT_IDS", "", "Chat IDs"),
            ("TELEGRAM_FIRST_ALERT_DELAY_MINUTES", "1", "Delay before 1st msg"),
            ("TELEGRAM_ALERT_FREQUENCY_MINUTES", "30", "Repeat every X mins"),
        ]
        for key, val, desc in defaults:
            if not session.get(Settings, key):
                session.add(Settings(key=key, value=val, description=desc))
        session.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global monitor_task
    init_db()
    seed_defaults()
    monitor_task = asyncio.create_task(start_monitor_loop())
    yield
    if monitor_task: monitor_task.cancel()
    try: await monitor_task
    except: pass

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_root(): return FileResponse('static/index.html')

@app.post("/api/monitor/restart")
async def restart_monitor():
    global monitor_task
    if monitor_task:
        monitor_task.cancel()
        try: await monitor_task
        except: pass
    monitor_task = asyncio.create_task(start_monitor_loop())
    return {"status": "restarted"}

# --- API ---
@app.get("/api/nvrs", response_model=list[NVR])
def get_nvrs(session: Session = Depends(get_session)):
    return session.exec(select(NVR)).all()

@app.post("/api/nvrs")
def create_nvr(nvr: NVR, session: Session = Depends(get_session)):
    session.add(nvr)
    session.commit()
    return nvr

@app.delete("/api/nvrs/{ip}")
def delete_nvr(ip: str, session: Session = Depends(get_session)):
    session.delete(session.get(NVR, ip))
    session.commit()
    return {"ok": True}

@app.get("/api/cameras", response_model=list[Camera])
def get_cameras(session: Session = Depends(get_session)):
    return session.exec(select(Camera).order_by(Camera.nvr_ip, Camera.channel_id)).all()

@app.put("/api/cameras/{id}")
def update_cam(id: int, p: dict, session: Session = Depends(get_session)):
    c = session.get(Camera, id)
    if "importance" in p: c.importance = int(p["importance"])
    session.add(c)
    session.commit()
    return c

@app.get("/api/settings", response_model=list[Settings])
def get_settings(session: Session = Depends(get_session)):
    return session.exec(select(Settings)).all()

@app.put("/api/settings/{key}")
def update_setting(key: str, p: Settings, session: Session = Depends(get_session)):
    s = session.get(Settings, key)
    s.value = p.value
    session.add(s)
    session.commit()
    return s

@app.get("/api/config/csv", response_class=PlainTextResponse)
def get_csv():
    if os.path.exists("camera_names.csv"):
        with open("camera_names.csv", "r", encoding="utf-8-sig") as f:
            return f.read()
    return ""

@app.post("/api/config/csv")
def save_csv(payload: CsvContent):
    with open("camera_names.csv", "w", encoding="utf-8-sig") as f:
        f.write(payload.content)
    return {"ok": True}

@app.get("/api/logs")
def search_logs(q: str = None, limit: int = 100, session: Session = Depends(get_session)):
    query = select(Log).order_by(Log.timestamp.desc()).limit(limit)
    if q: query = query.where(col(Log.message).contains(q) | col(Log.camera_name).contains(q))
    logs = session.exec(query).all()
    
    output = []
    for l in logs:
        jd = jdatetime.datetime.fromgregorian(datetime=l.timestamp)
        shamsi_str = jd.strftime("%Y/%m/%d %H:%M")
        item = l.model_dump()
        item['shamsi_date'] = shamsi_str
        output.append(item)
    return output