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
from alerts import send_email_raw, send_telegram_raw, get_config_dict

class CsvContent(BaseModel):
    content: str

monitor_task = None

def seed_defaults():
    with Session(engine) as session:
        defaults = [
            ("MAIL_ENABLED", "false", "Enable Email"),
            ("MAIL_SERVER", "smtp.gmail.com", "Server"),
            ("MAIL_PORT", "587", "Port"),
            ("MAIL_USER", "email@gmail.com", "User"),
            ("MAIL_PASS", "password", "Pass"),
            ("MAIL_RECIPIENTS", "admin@example.com", "Recipients"),
            ("MAIL_FIRST_ALERT_DELAY_MINUTES", "1", "Delay"),
            ("MAIL_ALERT_FREQUENCY_MINUTES", "60", "Frequency"),
            ("MAIL_MUTE_AFTER_N_ALERTS", "3", "Mute After N"),
            ("TELEGRAM_ENABLED", "false", "Enable Telegram"),
            ("TELEGRAM_BOT_TOKEN", "", "Bot Token"),
            ("TELEGRAM_CHAT_IDS", "", "Chat IDs"),
            ("TELEGRAM_PROXY", "", "Proxy URL (http://1.2.3.4:8080)"),
            ("TELEGRAM_FIRST_ALERT_DELAY_MINUTES", "1", "Delay"),
            ("TELEGRAM_ALERT_FREQUENCY_MINUTES", "30", "Frequency"),
            ("TELEGRAM_MUTE_AFTER_N_ALERTS", "3", "Mute After N"),
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

# --- TEST ENDPOINTS (FIXED) ---
@app.post("/api/test/email")  # <--- CHANGED FROM 'mail' TO 'email'
def test_mail():
    conf = get_config_dict()
    res = send_email_raw(conf, "HikStatus Test", "<h3>Test Successful</h3><p>Your email config is working.</p>")
    if res is True: return {"status": "ok"}
    raise HTTPException(status_code=400, detail=str(res))

@app.post("/api/test/telegram")
def test_telegram():
    conf = get_config_dict()
    res = send_telegram_raw(conf, "✅ *HikStatus Test*\nYour Telegram config is working.")
    if res is True: return {"status": "ok"}
    raise HTTPException(status_code=400, detail=str(res))

# --- API ---
@app.get("/api/nvrs", response_model=list[NVR])
def get_nvrs(session: Session = Depends(get_session)): return session.exec(select(NVR)).all()

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
def get_cameras(session: Session = Depends(get_session)): return session.exec(select(Camera).order_by(Camera.nvr_ip, Camera.channel_id)).all()

@app.put("/api/cameras/{id}")
def update_cam(id: int, p: dict, session: Session = Depends(get_session)):
    c = session.get(Camera, id)
    if "importance" in p: c.importance = int(p["importance"])
    session.add(c)
    session.commit()
    return c

@app.get("/api/settings", response_model=list[Settings])
def get_settings(session: Session = Depends(get_session)): return session.exec(select(Settings)).all()

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
        with open("camera_names.csv", "r", encoding="utf-8-sig") as f: return f.read()
    return ""

@app.post("/api/config/csv")
def save_csv(payload: CsvContent):
    with open("camera_names.csv", "w", encoding="utf-8-sig") as f: f.write(payload.content)
    return {"ok": True}

@app.get("/api/logs")
def search_logs(q: str = None, limit: int = 100, session: Session = Depends(get_session)):
    query = select(Log).order_by(Log.timestamp.desc()).limit(limit)
    if q: query = query.where(col(Log.details).contains(q) | col(Log.log_type).contains(q))
    logs = session.exec(query).all()
    
    output = []
    for l in logs:
        jd = jdatetime.datetime.fromgregorian(datetime=l.timestamp)
        shamsi_str = jd.strftime("%Y/%m/%d %H:%M")
        item = l.model_dump()
        item['shamsi_date'] = shamsi_str
        output.append(item)
    return output