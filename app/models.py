from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import uuid

class ProxyConfig(BaseModel):
    type: str = "http"  # http, https, socks5, socks4
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None

class ProfileCreate(BaseModel):
    name: str
    os: str = "windows"  # windows, macos, linux, random
    browser: str = "chromium"  # camoufox, chromium
    proxy: Optional[ProxyConfig] = None
    notes: Optional[str] = None
    fingerprint_preset: bool = True  # use real device presets

class Profile(BaseModel):
    id: str
    name: str
    os: str
    browser: str
    proxy: Optional[ProxyConfig] = None
    notes: Optional[str] = None
    fingerprint: Dict[str, Any] = {}
    user_data_dir: str
    created_at: str
    auto_random_fp: bool = False
    last_used: Optional[str] = None
    status: str = "idle"  # idle, running
    extensions: str = ""

    @staticmethod
    def generate_id():
        return uuid.uuid4().hex[:12]

class LaunchRequest(BaseModel):
    headless: bool = False
    auto_random_fp: bool = False
    startup_urls: Optional[str] = None
    startup_mode: Optional[str] = None
    enable_ext_btn2: bool = False
    enable_ext: bool = False


class CheckVideoReq(BaseModel):
    profile_id: str
    is_headless: bool = False
