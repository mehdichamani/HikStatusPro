import asyncio
import os
import jdatetime
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from sqlmodel import Session, select, col
from database import init_db, get_session, Camera, Log, NVR, Settings, DowntimeEvent, engine
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

# --- TEST ENDPOINTS ---
@app.post("/api/test/email")
def test_mail():
    conf = get_config_dict()
    res = send_email_raw(conf, "HikStatus Test", "<h3>Test Successful</h3>")
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
def search_logs(q: str = None, limit: int = 50, offset: int = 0, session: Session = Depends(get_session)):
    query = select(Log).order_by(Log.timestamp.desc()).offset(offset).limit(limit)
    if q: 
        # Handle "Type" filtering or generic search
        if q.lower() in ['camera', 'telegram', 'mail', 'service']:
            query = query.where(col(Log.log_type) == q)
        else:
            query = query.where(col(Log.details).contains(q) | col(Log.log_type).contains(q))
    
    logs = session.exec(query).all()
    
    output = []
    # Persian months mapping
    months = {1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد', 4: 'تیر', 5: 'مرداد', 6: 'شهریور', 7: 'مهر', 8: 'آبان', 9: 'آذر', 10: 'دی', 11: 'بهمن', 12: 'اسفند'}
    # Persian days mapping
    days = {'Sat': 'شنبه', 'Sun': 'یکشنبه', 'Mon': 'دوشنبه', 'Tue': 'سه‌شنبه', 'Wed': 'چهارشنبه', 'Thu': 'پنج‌شنبه', 'Fri': 'جمعه'}

    for l in logs:
        jd = jdatetime.datetime.fromgregorian(datetime=l.timestamp)
        day_name = days[l.timestamp.strftime("%a")]
        month_name = months[jd.month]
        # Format: شنبه 15 آذر 1404 15:30
        shamsi_str = f"{day_name} {jd.day} {month_name} {jd.year} {jd.strftime('%H:%M')}"
        
        item = l.model_dump()
        item['shamsi_date'] = shamsi_str
        
        # Calculate downtime for logs if needed (rudimentary check)
        # This is mostly visual; precise calculation is in reports
        # If the detail string contains "Offline", we assume it's an event start
        
        output.append(item)
    return output

def calculate_downtime(session, cam_id, hours):
    now = datetime.now()
    cutoff = now - timedelta(hours=hours)
    events = session.exec(select(DowntimeEvent).where(
        DowntimeEvent.camera_id == cam_id,
        (DowntimeEvent.end_time == None) | (DowntimeEvent.end_time > cutoff)
    )).all()
    
    total_minutes = 0
    for e in events:
        start = max(e.start_time, cutoff)
        end = min(e.end_time or now, now)
        if end > start:
            total_minutes += (end - start).total_seconds() / 60
    return int(total_minutes)

@app.get("/api/stats/{cam_id}")
def get_cam_stats(cam_id: int, session: Session = Depends(get_session)):
    down_1h = calculate_downtime(session, cam_id, 1)
    down_24h = calculate_downtime(session, cam_id, 24)
    return {"down_1h": down_1h, "down_24h": down_24h}

@app.get("/api/reports/overview")
def get_reports(session: Session = Depends(get_session)):
    cameras = session.exec(select(Camera)).all()
    list_1h = []
    list_24h = []
    
    for c in cameras:
        d1 = calculate_downtime(session, c.id, 1)
        d24 = calculate_downtime(session, c.id, 24)
        
        if d1 > 0:
            list_1h.append({"name": c.name, "ip": c.ip, "mins": d1})
        if d24 > 0:
            list_24h.append({"name": c.name, "ip": c.ip, "mins": d24})
            
    # Sort Descending
    list_1h.sort(key=lambda x: x['mins'], reverse=True)
    list_24h.sort(key=lambda x: x['mins'], reverse=True)
    
    return {"last_1h": list_1h, "last_24h": list_24h}