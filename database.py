from sqlmodel import SQLModel, Field, create_engine, Session
from datetime import datetime
from typing import Optional

class NVR(SQLModel, table=True):
    ip: str = Field(primary_key=True)
    user: str
    password: Optional[str] = None
    enabled: bool = True

class Camera(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    ip: str
    nvr_ip: str = Field(index=True)
    channel_id: str
    is_muted: bool = False
    importance: int = Field(default=2)
    last_online: Optional[datetime] = None
    status: str = "Unknown"
    
    mail_alert_count: int = 0
    mail_last_alert: Optional[datetime] = None
    telegram_alert_count: int = 0
    telegram_last_alert: Optional[datetime] = None

class Log(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.now)
    log_type: str  # Camera, Mail, Telegram, Service
    state: str     # Online/Offline, Sent/Failed, Started/Stopped
    details: str   # Detail message

class Settings(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    description: Optional[str] = None

sqlite_file_name = "data/monitor.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def init_db():
    import os
    os.makedirs("data", exist_ok=True)
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session