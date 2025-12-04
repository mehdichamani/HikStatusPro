import asyncio
import requests
import xml.etree.ElementTree as ET
import csv
import os
from datetime import datetime, timedelta
from requests.auth import HTTPDigestAuth
from sqlmodel import Session, select
from database import engine, NVR, Camera, Log, Settings
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

def poll_nvr_thread(nvr_data):
    ip, user, password = nvr_data
    url = f"http://{ip}/ISAPI/ContentMgmt/InputProxy/channels/status"
    try:
        resp = requests.get(url, auth=HTTPDigestAuth(user, password), timeout=6)
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
    """Checks all cameras and returns lists of messages to send."""
    alerts = []
    recoveries = []
    now = datetime.now()

    # Load Settings
    mail_delay = int(get_setting(session, "MAIL_FIRST_ALERT_DELAY_MINUTES", 1))
    mail_freq = int(get_setting(session, "MAIL_ALERT_FREQUENCY_MINUTES", 60))
    tele_delay = int(get_setting(session, "TELEGRAM_FIRST_ALERT_DELAY_MINUTES", 1))
    tele_freq = int(get_setting(session, "TELEGRAM_ALERT_FREQUENCY_MINUTES", 30))

    for cam in cams_to_check:
        # --- RECOVERY LOGIC ---
        if cam.status == "Online":
            # If it was offline and we haven't reset the counters yet, it means it just came back
            if cam.mail_alert_count > 0 or cam.telegram_alert_count > 0:
                downtime = now - (cam.last_online or now) # approximate since last_online is update on online
                recoveries.append(f"✅ {cam.name} is back Online")
                
                # Reset counters
                cam.mail_alert_count = 0
                cam.telegram_alert_count = 0
                session.add(cam)
            continue

        # --- FAILURE LOGIC ---
        downtime = now - (cam.last_online or now)
        downtime_mins = int(downtime.total_seconds() / 60)

        # Telegram Rules
        send_tele = False
        if cam.telegram_alert_count == 0:
            if downtime_mins >= tele_delay: send_tele = True
        else:
            last = cam.telegram_last_alert or now
            if (now - last).total_seconds() / 60 >= tele_freq: send_tele = True
        
        if send_tele:
            alerts.append(f"🚨 {cam.name} ({downtime_mins}m)")
            cam.telegram_alert_count += 1
            cam.telegram_last_alert = now
            session.add(cam)

    return alerts, recoveries

async def start_monitor_loop():
    print("👀 Monitor loop started...")
    last_summary_hour = -1
    
    while True:
        try:
            name_map = load_csv_names()
            with Session(engine) as session:
                nvrs = session.exec(select(NVR).where(NVR.enabled == True)).all()

            if not nvrs:
                await asyncio.sleep(10)
                continue
            
            # Parallel Polling
            tasks = [asyncio.to_thread(poll_nvr_thread, (n.ip, n.user, n.password)) for n in nvrs]
            results = await asyncio.gather(*tasks)

            cams_processed = []

            with Session(engine) as session:
                for nvr_obj, res in zip(nvrs, results):
                    status, payload = res
                    if status == "FAIL":
                        session.add(Log(level="ERROR", message=f"NVR {nvr_obj.ip} Error: {payload}"))
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
                        else:
                            if csv_name and db_cam.name != csv_name: db_cam.name = csv_name
                            if db_cam.ip != d['ip']: db_cam.ip = d['ip']
                            if db_cam.status != new_status:
                                session.add(Log(level="WARNING" if new_status=="Offline" else "SUCCESS", camera_name=db_cam.name, message=f"Camera is now {new_status}"))
                                db_cam.status = new_status
                            
                            if d['online']: db_cam.last_online = datetime.now()
                            session.add(db_cam)
                        
                        cams_processed.append(db_cam)

                # --- BATCH ALERTS ---
                alerts, recoveries = await process_batch_alerts(session, cams_processed)
                
                # Send Batch Telegram
                if alerts:
                    await asyncio.to_thread(send_telegram_batch, "⚠️ Cameras Offline", alerts)
                if recoveries:
                    await asyncio.to_thread(send_telegram_batch, "✅ Cameras Recovered", recoveries)

                # --- HOURLY SUMMARY ---
                now = datetime.now()
                if now.minute == 0 and now.hour != last_summary_hour:
                    offline_cams = [c for c in cams_processed if c.status == "Offline"]
                    if offline_cams:
                        lines = [f"{c.name} ({c.ip})" for c in offline_cams]
                        await asyncio.to_thread(send_telegram_batch, f"📊 Hourly Summary ({len(lines)} Offline)", lines)
                    last_summary_hour = now.hour

                session.commit()
            
            # FIXED POLL INTERVAL
            await asyncio.sleep(60) 

        except asyncio.CancelledError: break
        except Exception as e: 
            print(f"Error: {e}")
            await asyncio.sleep(5)