import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from database import Session, engine, Settings

def get_config_dict():
    with Session(engine) as session:
        settings = session.query(Settings).all()
        return {s.key: s.value for s in settings}

def send_email_batch(subject, lines):
    conf = get_config_dict()
    if conf.get("MAIL_ENABLED") != "true" or not lines: return False
    return send_email_raw(conf, subject, "<h3>System Alert</h3><ul>" + "".join([f"<li>{l}</li>" for l in lines]) + "</ul>")

def send_email_raw(conf, subject, body):
    try:
        sender = conf.get("MAIL_USER")
        recipients = conf.get("MAIL_RECIPIENTS", "").split(",")
        server = conf.get("MAIL_SERVER")
        port = int(conf.get("MAIL_PORT", 587))
        password = conf.get("MAIL_PASS")
        
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = ", ".join(recipients)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP(server, port) as s:
            s.starttls()
            s.login(sender, password)
            s.sendmail(sender, recipients, msg.as_string())
        return True
    except Exception as e:
        print(f"📧 Mail Error: {e}")
        return str(e)

def send_telegram_batch(header, lines):
    conf = get_config_dict()
    if conf.get("TELEGRAM_ENABLED") != "true" or not lines: return False
    msg = f"*{header}*\n" + "\n".join(lines)
    return send_telegram_raw(conf, msg)

def send_telegram_raw(conf, message):
    token = conf.get("TELEGRAM_BOT_TOKEN")
    raw_ids = conf.get("TELEGRAM_CHAT_IDS", "")
    proxy_url = conf.get("TELEGRAM_PROXY", "")
    
    if not token or not raw_ids: return "Missing Token/ID"
    
    chat_ids = [c.strip() for c in raw_ids.split(",") if c.strip()]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    # Configure Proxy
    proxies = {'https': proxy_url, 'http': proxy_url} if proxy_url else None

    errors = []
    for cid in chat_ids:
        try:
            payload = {'chat_id': cid, 'text': message, 'parse_mode': 'Markdown'}
            requests.post(url, data=payload, proxies=proxies, timeout=10)
        except Exception as e:
            print(f"✈️ Telegram Error: {e}")
            errors.append(str(e))
            
    return errors[0] if errors else True