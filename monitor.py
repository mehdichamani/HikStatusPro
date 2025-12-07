import asyncio
import requests
import xml.etree.ElementTree as ET
import csv
import os
from datetime import datetime, timedelta
from requests.auth import HTTPDigestAuth
from sqlmodel import Session, select
from database import engine, NVR, Camera, Log, Settings, DowntimeEvent
from alerts import send_email_batch, send_telegram_batch

def get_setting(session, key, default):
    s = session.get(Settings, key)
    return s.value if s else default

def load_csv_names():
    mapping = {}
    if os.path.exists("camera_names.csv"):
        try:
            with open("camera_names.csv", "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) >= 2 and row[0].strip():
                        mapping[row[0].strip()] = row[1].strip()
        except: pass
    return mapping

def log_event(session, l_type, state, details):
    try:
        session.add(Log(log_type=l_type, state=state, details=details))
        session.commit() 
    except: pass

def poll_nvr_thread(nvr_data):
    ip, user, password = nvr_data
    url = f"http://{ip}/ISAPI/ContentMgmt/InputProxy/channels/status"
    try:
        resp = requests.get(url, auth=HTTPDigestAuth(user, password), timeout=6, proxies={})
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            namespace = {'ns': 'http://www.hikvision.com/ver20/XMLSchema'}
            results = []
            for channel in root.findall('ns:InputProxyChannelStatus', namespace):
                chan_id = channel.find('ns:id', namespace).text
                online = channel.find('ns:online', namespace).text == 'true'
                port = channel.find('ns:sourceInputPortDescriptor', namespace)
                cam_ip = port.find('ns:ipAddress', namespace).text if port is not None else "0.0.0.0"
                results.append({"channel_id": chan_id, "ip": cam_ip, "online": online})
            return ("OK", results)
        return ("FAIL", f"HTTP {resp.status_code}")
    except Exception as e:
        return ("FAIL", str(e))

async def process_batch_alerts(session, cams_to_check):
    tele_alerts = []
    mail_alerts = []
    tele_recoveries = []
    mail_recoveries = []
    now = datetime.now()

    # Load Settings
    mail_delay = int(get_setting(session, "MAIL_FIRST_ALERT_DELAY_MINUTES", 1))
    mail_freq = int(get_setting(session, "MAIL_ALERT_FREQUENCY_MINUTES", 60))
    mail_mute = int(get_setting(session, "MAIL_MUTE_AFTER_N_ALERTS", 3))

    tele_delay = int(get_setting(session, "TELEGRAM_FIRST_ALERT_DELAY_MINUTES", 1))
    tele_freq = int(get_setting(session, "TELEGRAM_ALERT_FREQUENCY_MINUTES", 30))
    tele_mute = int(get_setting(session, "TELEGRAM_MUTE_AFTER_N_ALERTS", 3))

    for cam in cams_to_check:
        # --- RECOVERY LOGIC ---
        if cam.status == "Online":
            if cam.telegram_alert_count > 0:
                tele_recoveries.append(f"✅ {cam.name} is back Online")
                cam.telegram_alert_count = 0
            if cam.mail_alert_count > 0:
                mail_recoveries.append(f"{cam.name} is back Online")
                cam.mail_alert_count = 0
            session.add(cam)
            continue

        # --- FAILURE LOGIC ---
        downtime = now - (cam.last_online or now)
        downtime_mins = int(downtime.total_seconds() / 60)

        # 1. Telegram Rules
        send_tele = False
        if cam.telegram_alert_count < tele_mute:
            if cam.telegram_alert_count == 0:
                # Importance Logic: Low (1) skips Delay, waits for Frequency
                threshold = tele_delay
                if cam.importance == 1: threshold = tele_freq
                
                if downtime_mins >= threshold: send_tele = True
            else:
                last = cam.telegram_last_alert or now
                if (now - last).total_seconds() / 60 >= tele_freq: send_tele = True
        
        if send_tele:
            msg = f"🚨 {cam.name} ({downtime_mins}m)"
            # Check if this is the last alert before muting
            if cam.telegram_alert_count + 1 >= tele_mute:
                msg += " 🔕(Muted)"
            
            tele_alerts.append(msg)
            cam.telegram_alert_count += 1
            cam.telegram_last_alert = now
            session.add(cam)

        # 2. Email Rules
        send_mail = False
        if cam.mail_alert_count < mail_mute:
            if cam.mail_alert_count == 0:
                # Importance Logic: Low (1) skips Delay, waits for Frequency
                threshold = mail_delay
                if cam.importance == 1: threshold = mail_freq

                if downtime_mins >= threshold: send_mail = True
            else:
                last = cam.mail_last_alert or now
                if (now - last).total_seconds() / 60 >= mail_freq: send_mail = True
        
        if send_mail:
            msg = f"{cam.name} is offline for {downtime_mins} mins"
            # Check if this is the last alert before muting
            if cam.mail_alert_count + 1 >= mail_mute:
                msg += " <b>(Alerts Muted)</b>"
                
            mail_alerts.append(msg)
            cam.mail_alert_count += 1
            cam.mail_last_alert = now
            session.add(cam)

    return tele_alerts, mail_alerts, tele_recoveries, mail_recoveries

async def start_monitor_loop():
    print("👀 Monitor loop started...")
    last_summary_hour = -1
    
    with Session(engine) as session:
        log_event(session, "Service", "Started", "Monitor loop initialized")

    while True:
        try:
            name_map = load_csv_names()
            with Session(engine) as session:
                nvrs = session.exec(select(NVR).where(NVR.enabled == True)).all()

            if not nvrs:
                await asyncio.sleep(10)
                continue
            
            tasks = [asyncio.to_thread(poll_nvr_thread, (n.ip, n.user, n.password)) for n in nvrs]
            results = await asyncio.gather(*tasks)

            cams_processed = []

            with Session(engine) as session:
                for nvr_obj, res in zip(nvrs, results):
                    status, payload = res
                    if status == "FAIL":
                        log_event(session, "Camera", "Error", f"NVR {nvr_obj.ip} Failed: {payload}")
                        continue
                        
                    for d in payload:
                        stmt = select(Camera).where(Camera.nvr_ip == nvr_obj.ip, Camera.channel_id == d['channel_id'])
                        db_cam = session.exec(stmt).first()
                        new_status = "Online" if d['online'] else "Offline"
                        
                        csv_name = name_map.get(d['ip'])
                        final_name = csv_name if csv_name else f"Ch {d['channel_id']}"

                        if not db_cam:
                            db_cam = Camera(name=final_name, ip=d['ip'], nvr_ip=nvr_obj.ip, channel_id=d['channel_id'], status=new_status, last_online=datetime.now() if d['online'] else None)
                            session.add(db_cam)
                            session.flush() 
                            session.refresh(db_cam)
                            if new_status == "Offline":
                                session.add(DowntimeEvent(camera_id=db_cam.id, start_time=datetime.now()))
                        else:
                            if csv_name and db_cam.name != csv_name: db_cam.name = csv_name
                            if db_cam.ip != d['ip']: db_cam.ip = d['ip']
                            
                            if db_cam.status != new_status:
                                log_event(session, "Camera", new_status, f"{db_cam.name} ({db_cam.ip})")
                                db_cam.status = new_status
                                if new_status == "Offline":
                                    session.add(DowntimeEvent(camera_id=db_cam.id, start_time=datetime.now()))
                                elif new_status == "Online":
                                    open_evt = session.exec(select(DowntimeEvent).where(DowntimeEvent.camera_id == db_cam.id, DowntimeEvent.end_time == None)).first()
                                    if open_evt:
                                        open_evt.end_time = datetime.now()
                                        session.add(open_evt)
                            
                            if d['online']: db_cam.last_online = datetime.now()
                            session.add(db_cam)
                        
                        cams_processed.append(db_cam)

                t_alerts, m_alerts, t_recov, m_recov = await process_batch_alerts(session, cams_processed)
                
                if t_alerts:
                    res = await asyncio.to_thread(send_telegram_batch, "⚠️ Cameras Offline", t_alerts)
                    log_event(session, "Telegram", "Sent" if res is True else "Failed", f"Sent {len(t_alerts)} alerts")
                if t_recov:
                    await asyncio.to_thread(send_telegram_batch, "✅ Cameras Recovered", t_recov)
                if m_alerts:
                    await asyncio.to_thread(send_email_batch, "⚠️ Cameras Offline Alert", m_alerts)
                if m_recov:
                    await asyncio.to_thread(send_email_batch, "✅ Cameras Recovered", m_recov)

                now = datetime.now()
                if now.minute == 0 and now.hour != last_summary_hour:
                    hour_start = now.replace(minute=0, second=0, microsecond=0)
                    summary_lines = []
                    for c in cams_processed:
                        if c.status == "Offline":
                            offline_since = c.last_online or now
                            overlap_start = max(hour_start, offline_since)
                            minutes_down = int((now - overlap_start).total_seconds() / 60)
                            if minutes_down > 0:
                                summary_lines.append(f"{c.name}: {minutes_down}m")

                    if summary_lines:
                        header = f"📊 Hourly Downtime Summary ({now.strftime('%H:00')})"
                        await asyncio.to_thread(send_telegram_batch, header, summary_lines)
                        log_event(session, "Telegram", "Sent", "Hourly Summary")
                    last_summary_hour = now.hour

                session.commit()
            
            await asyncio.sleep(60) 

        except asyncio.CancelledError:
            break
        except Exception as e: 
            print(f"Error: {e}")
            await asyncio.sleep(5)