# -*- coding: utf-8 -*-
"""
hma_app_switcher.py — Doi IP bang app HMA VPN tren Windows,
KHONG chiem quyen chuot (dung UI Automation: Invoke/Toggle pattern).

Dieu kien:
    1. pip install pywinauto
    2. App HMA VPN phai dang chay va cua so dang MO
       (minimize xuong taskbar duoc; neu an han vao tray thi khong thay duoc)

Lenh:
    python hma_app_switcher.py status              # trang thai VPN + IP hien tai
    python hma_app_switcher.py connect             # bat VPN
    python hma_app_switcher.py switch              # doi IP (reconnect, cung location)
    python hma_app_switcher.py country "USA"       # doi sang nuoc chi dinh
    python hma_app_switcher.py randomcountry       # doi sang mot nuoc NGAU NHIEN
    python hma_app_switcher.py debug               # in cac nut bam cua app
    python hma_app_switcher.py debugloc            # in cac phan tu o man hinh chon nuoc
    python hma_app_switcher.py countries           # in danh sach nuoc ho tro random
"""

import random, re, sys, time, ctypes, threading, subprocess, urllib.request
from ctypes import wintypes as _wt
from pywinauto import Desktop, Application

VPN_EXE = r"C:\Program Files\Privax\HMA VPN\Vpn.exe"   # chi dung de MO app neu chua chay
SWITCH_AUTO_IDS = ["dashboard_switch", "ConnectButton"]
LOCPICK_AUTO_IDS = ["dashboard_chooseLocation"]

# Danh sach quoc gia trong app HMA (khop danh sach tren may ban)
COUNTRIES = [
    "Albania", "Argentina", "Australia", "Austria", "Azerbaijan", "Bangladesh",
    "Belgium", "Bosnia & Herzegovina", "Brazil", "Brunei", "Bulgaria", "Cambodia",
    "Canada", "Chile", "Colombia", "Costa Rica", "Croatia", "Cyprus",
    "Czech Republic", "Denmark", "Ecuador", "Estonia", "Finland", "France",
    "Germany", "Greece", "Hong Kong", "Hungary", "Iceland", "India", "Indonesia",
    "Ireland", "Israel", "Italy", "Japan", "Laos", "Latvia", "Libya", "Lithuania",
    "Luxembourg", "Malaysia", "Mexico", "Moldova", "Morocco", "Netherlands",
    "New Zealand", "Nigeria", "Norway", "Pakistan", "Panama", "Peru",
    "Philippines", "Poland", "Portugal", "Qatar", "Romania", "Saudi Arabia",
    "Serbia", "Singapore", "Slovakia", "South Africa", "South Korea", "Spain",
    "Sri Lanka", "Sweden", "Switzerland", "Taiwan", "Thailand", "Tunisia",
    "Türkiye", "Ukraine", "United Arab Emirates", "United Kingdom",
    "United States", "Uzbekistan", "Vietnam",
]

# Ten tat -> ten day du (tranh go "uk" bi nham "Ukraine")
ALIASES = {
    "uk": "United Kingdom", "gb": "United Kingdom", "anh": "United Kingdom",
    "usa": "United States", "us": "United States", "my": "United States",
    "uae": "United Arab Emirates", "korea": "South Korea", "hongkong": "Hong Kong",
    "turkey": "Türkiye", "czech": "Czech Republic", "nz": "New Zealand",
    "sa": "South Africa", "p2p": "P2P-Optimized Region",
}

_CACHE = {"dlg": None}   # cache cua so de khong phai quet process lien tuc
COUNTRY_SET = set(COUNTRIES)


# ----------------- tien ich -----------------

def public_ip():
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            return urllib.request.urlopen(url, timeout=8).read().decode().strip()
        except Exception:
            continue
    return "?"


# ------- ghi nho & phuc hoi cua so dang focus (de khong lam ban mat cho go) -------
_user32 = ctypes.windll.user32

def _save_foreground():
    try:
        return _user32.GetForegroundWindow() or None
    except Exception:
        return None

def _restore_foreground(hwnd):
    if not hwnd:
        return
    try:
        fg = _user32.GetForegroundWindow()
        tid_fg = _user32.GetWindowThreadProcessId(fg, None)
        tid_cur = ctypes.windll.kernel32.GetCurrentThreadId()
        _user32.AttachThreadInput(tid_cur, tid_fg, True)
        _user32.SetForegroundWindow(hwnd)
        _user32.AttachThreadInput(tid_cur, tid_fg, False)
    except Exception:
        pass


SW_MINIMIZE = 6          # thu nho
SW_SHOWNOACTIVATE = 4    # mo lai, KHONG chiem focus

def _show_window(hwnd, cmd):
    try:
        _user32.ShowWindow(hwnd, cmd)
        return True
    except Exception:
        return False

def _is_iconic(hwnd):
    try:
        return bool(_user32.IsIconic(hwnd))
    except Exception:
        return False

def _enable_window(hwnd, enable):
    """EnableWindow(false): cua so van hien/ve binh thuong nhung KHONG nhan
    chuot/ban phim tu nguoi dung. UIA invoke van bam duoc vi khong qua input that."""
    try:
        _user32.EnableWindow(hwnd, bool(enable))
        return True
    except Exception:
        return False


class _FocusGuard:
    """Luong chay nen trong luc thao tac: app HMA hong duoc chiem focus ban phim.
    Cu thay HMA giat focus la lap tuc (50ms) tra lai ve cua so nguoi dung."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self._hma_hwnds = set()
        self._user_hwnd = None

    def _collect_hma_hwnds(self):
        hwnds = set()
        for pid in _hma_pids():
            for w in _windows_of_pid(pid):
                try:
                    hwnds.add(w.handle)
                except Exception:
                    pass
        return hwnds

    def start(self):
        self._hma_hwnds = self._collect_hma_hwnds()
        try:
            fg = _user32.GetForegroundWindow()
            if fg and fg not in self._hma_hwnds:
                self._user_hwnd = fg           # cua so ban dang lam viec
        except Exception:
            pass
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        ticks = 0
        while not self._stop.is_set():
            ticks += 1
            if ticks % 20 == 0:                # lam moi danh sach cua so HMA moi giay
                self._hma_hwnds = self._collect_hma_hwnds()
            try:
                fg = _user32.GetForegroundWindow()
                if fg:
                    if fg in self._hma_hwnds:
                        if self._user_hwnd:
                            _restore_foreground(self._user_hwnd)
                    else:
                        self._user_hwnd = fg   # ban alt-tab sang app khac -> nho cai moi
            except Exception:
                pass
            time.sleep(0.03)

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            try:
                self._thread.join(timeout=2)
            except Exception:
                pass


# ----------------- khoa go phim tam thoi (chuot van dung) -----------------
_WH_KEYBOARD_LL = 13
_LLKB_PROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                ctypes.c_size_t, ctypes.c_size_t)
try:
    _user32.SetWindowsHookExW.restype = ctypes.c_void_p
    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.c_uint]
    _user32.CallNextHookEx.restype = ctypes.c_ssize_t
    _user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                       ctypes.c_size_t, ctypes.c_size_t]
    _user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    _k32 = ctypes.windll.kernel32
    _k32.GetModuleHandleW.restype = ctypes.c_void_p
    _k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
except Exception:
    pass


class _KeyboardBlock:
    """Chan phim go VAT LY cua nguoi dung trong thoi gian ngan.
    Phim do script tu go (injected) van di qua duoc; chuot dung binh thuong."""

    def __init__(self):
        self._thread = None
        self._stop_ev = threading.Event()
        self._hook = None
        self._cb = None

    def start(self):
        self._stop_ev.clear()
        self._hook = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        # cho hook cai dat xong, bao cao trang thai
        deadline = time.time() + 3
        while self._hook is None and self._thread.is_alive() and time.time() < deadline:
            time.sleep(0.02)
        print("[KeyboardBlock]", "DA CHAN go phim cua ban (tam thoi)"
              if self._hook else "!! KHONG chan duoc - bao loi cho toi")

    def stop(self):
        self._stop_ev.set()
        if self._thread is not None:
            try:
                self._thread.join(timeout=3)
            except Exception:
                pass
        if self._hook is None and self._stop_ev.is_set():
            print("[KeyboardBlock] Da tra lai ban phim")

    def _loop(self):
        def proc(nCode, wParam, lParam):
            if nCode == 0:
                # KBDLLHOOKSTRUCT: vkCode(0), scanCode(4), flags(8)
                flags = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_uint32))[2]
                if not (flags & 0x10):          # LLKHF_INJECTED: phim cua NGUOI DUNG
                    return 1                    # nuot phim
            return _user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._cb = _LLKB_PROC(proc)             # giu tham chieu, tranh GC
        hmod = ctypes.windll.kernel32.GetModuleHandleW(None)
        self._hook = _user32.SetWindowsHookExW(_WH_KEYBOARD_LL, self._cb, hmod, 0)

        msg = _wt.MSG()
        while not self._stop_ev.is_set():
            while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.01)
        if self._hook:
            try:
                _user32.UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
            self._hook = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


def _hma_pids():
    pids = []
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return pids
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.split('","')]
        if len(parts) >= 2:
            name = parts[0].lower()
            if "hma" in name or "vpn" in name:
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    pass
    return pids


def _windows_of_pid(pid, visible=True):
    try:
        app = Application(backend="uia").connect(process=pid, timeout=3)
        return app.windows(visible_only=visible, top_level_only=True)
    except Exception:
        return []


def get_dialog(refresh=False):
    """Tim cua so app HMA (co cache de chay nhanh)."""
    if not refresh and _CACHE["dlg"] is not None:
        try:
            _CACHE["dlg"].window_text()
            return _CACHE["dlg"]
        except Exception:
            _CACHE["dlg"] = None

    found_any = []
    for pid in _hma_pids():
        for w in _windows_of_pid(pid):
            try:
                t = (w.window_text() or "").strip()
            except Exception:
                continue
            if not t:
                continue
            found_any.append((w, t))
            if "hma" in t.lower():
                _CACHE["dlg"] = w
                return w
    if found_any:
        _CACHE["dlg"] = found_any[0][0]
        return found_any[0][0]

    try:
        dlg = Desktop(backend="uia").window(title="HMA")
        dlg.wrapper_object()
        _CACHE["dlg"] = dlg
        return dlg
    except Exception:
        pass

    try:
        Application(backend="uia").start(VPN_EXE, wait_for_idle=False)
        time.sleep(10)
        dlg = Desktop(backend="uia").window(title="HMA")
        dlg.wrapper_object()
        _CACHE["dlg"] = dlg
        return dlg
    except Exception:
        pass

    print("[DEBUG] Khong tim thay app HMA. Cac cua so dang mo tren may:")
    try:
        for w in Desktop(backend="uia").windows():
            try:
                t = (w.window_text() or "").strip()
                if t:
                    print("   -", repr(t))
            except Exception:
                pass
    except Exception:
        pass
    raise RuntimeError(
        "Khong tim thay cua so app HMA. Hay MO cua so app HMA len "
        "(neu dang an duoi tray thi click icon de hien cua so) roi chay lai.")


def _find_button(dlg, auto_ids, name_regex):
    buttons = dlg.descendants(control_type="Button")
    for b in buttons:
        if b.automation_id() in auto_ids:
            return b
    for b in buttons:
        if re.search(name_regex, b.window_text() or "", re.I):
            return b
    raise RuntimeError(
        "Khong tim thay nut. Chay muc 4 - Debug de xem lai danh sach nut.")


def _switch_button(dlg):
    return _find_button(dlg, SWITCH_AUTO_IDS, r"connect|disconnect")


def _press(button):
    """Nhan nut KHONG dung chuot vat ly."""
    try:
        button.invoke()
    except Exception:
        try:
            button.toggle()
        except Exception:
            button.set_focus()
            button.type_keys("{ENTER}", set_foreground=False)


def _is_on(btn):
    try:
        return btn.get_toggle_state() == 1
    except Exception:
        pass
    try:
        return "disconnect" in (btn.window_text() or "").lower()
    except Exception:
        return False


def _wait_new_ip(old_ip, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.5)
        new_ip = public_ip()
        if new_ip != "?" and new_ip != old_ip:
            return new_ip
    return None


# ----------------- chuc nang chinh -----------------

def is_connected():
    try:
        return _is_on(_switch_button(get_dialog()))
    except Exception:
        return False


def _switch_button_retry(timeout=12):
    """Tim cong tac ON/OFF, thu lai nhieu lan neu app dang chuyen giao dien."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return _switch_button(get_dialog())
        except Exception:
            time.sleep(0.6)
    return None


def _ensure_vpn_on(total=40):
    """Bat VPN neu dang tat; chiu loi tam thoi khi UI dang doi man hinh."""
    deadline = time.time() + total
    pressed = False
    while time.time() < deadline:
        try:
            btn = _switch_button(get_dialog())
            if _is_on(btn):
                return True
            if not pressed:
                _press(btn)
                pressed = True
        except Exception:
            pass                        # UI dang chuyen man hinh -> thu lai
        time.sleep(0.8)
    return False


def connect():
    if _ensure_vpn_on():
        print("Da ket noi VPN. IP:", public_ip())
        return True
    print("Chua ket noi duoc (app dang chuyen man hinh?) - thu lai sau")
    return False


def status():
    get_dialog()
    print("VPN:", "DA KET NOI" if is_connected() else "CHUA KET NOI")
    print("IP hien tai:", public_ip())


def switch_ip():
    """Doi IP bang cach reconnect (giu nguyen location)."""
    guard = _FocusGuard()              # linh gac focus
    guard.start()
    try:
        if not is_connected():
            print("VPN dang tat, dang ket noi...")
            if not connect():
                return None

        old_ip = public_ip()
        print("Dang doi IP (reconnect)...")
        for attempt in (1, 2):
            btn = _switch_button_retry()
            if btn is None:
                print("Khong tim thay cong tac ON/OFF - thu lai sau")
                return None
            _press(btn)                 # TAT
            time.sleep(2.5)
            btn = _switch_button_retry()
            if btn is not None:
                _press(btn)             # BAT lai
            new_ip = _wait_new_ip(old_ip)
            if new_ip:
                print("IP cu :", old_ip)
                print("IP moi:", new_ip)
                return new_ip
            if attempt == 1:
                print("IP chua doi, reconnect them lan nua...")
        print("IP van la", public_ip(), "(server gan lai cung IP - thu lai sau)")
        return None
    finally:
        guard.stop()


# ----------------- doi sang nuoc khac -----------------

def _all_hma_windows():
    wins = []
    for pid in _hma_pids():
        wins.extend(_windows_of_pid(pid))
    return wins


def _confirm_disconnect_continue(timeout=8):
    """Tu bam popup 'DISCONNECT & CONTINUE?' khi doi nuoc luc VPN ON.
    Quet ca cua so dang minimize/an cua app HMA."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        targets = []
        try:
            targets.append(get_dialog())
        except Exception:
            pass
        for pid in _hma_pids():
            targets.extend(_windows_of_pid(pid, visible=False))
        for w in targets:
            try:
                for b in w.descendants(control_type="Button"):
                    nm = (b.window_text() or "").lower()
                    if "continue" in nm and "cancel" not in nm:
                        print("Xac nhan popup:", b.window_text())
                        _press(b)
                        return True
            except Exception:
                continue
        time.sleep(0.4)
    return False


def _set_edit_text(edit, text):
    """Ghi text vao o Edit: uu tien cach KHONG dung phim that."""
    try:
        edit.set_value("")
    except Exception:
        try:
            edit.set_window_text("")
        except Exception:
            pass
    try:
        edit.set_value(text)             # ValuePattern - khong can focus/phim
        return True
    except Exception:
        pass
    try:
        edit.set_window_text(text)       # LegacyIAccessible SetValue
        return True
    except Exception:
        pass
    # Cuoi cung: go phim ao (phim nguoi dung dang bi chan, injected van qua)
    edit.set_focus()
    edit.type_keys("^a{DELETE}" + text, pause=0.01)
    return True


def _open_location_picker(dlg):
    btn = _find_button(dlg, LOCPICK_AUTO_IDS, r"location")
    _press(btn)
    time.sleep(2.5)


# ----------------- cuon & quet danh sach quoc gia (KHONG go phim) -----------------

def _scroll_list(dlg):
    """Cuon danh sach quoc gia xuong bang ScrollPattern (khong dung chuot/phim).
    Tra ve False neu khong tim duoc dieu khien cuon."""
    for ctype in ("List", "Custom", "Pane", "Group", "Document"):
        try:
            els = dlg.descendants(control_type=ctype)
        except Exception:
            continue
        for e in els:
            try:
                pat = e.iface_scroll
                if pat.VerticallyScrollable and float(pat.VerticalScrollPercent) < 98.0:
                    pat.Scroll(2, 4)     # ngang: NoAmount, doc: LargeIncrement
                    return True
            except Exception:
                continue
    return False


def _collect_country_items(dlg):
    """Thu thap cac muc quoc gia dang hien thi (ten khop dung trong danh sach)."""
    found = {}
    for ctype in ("Button", "ListItem", "TreeItem", "Custom", "Text"):
        try:
            els = dlg.descendants(control_type=ctype)
        except Exception:
            continue
        for e in els:
            try:
                name = (e.window_text() or "").strip()
            except Exception:
                continue
            if name not in COUNTRY_SET:
                continue
            if ctype == "Text":                      # leo len cha bam duoc
                cur = e
                for _ in range(6):
                    try:
                        cur = cur.parent()
                        if cur.element_info.control_type in ("Button", "ListItem", "Custom", "Pane"):
                            e = cur
                            break
                    except Exception:
                        break
            found.setdefault(name, (e, name))
    return list(found.values())


def _scroll_find_country(dlg, country, max_steps=40):
    """Cuon danh sach A-Z cho toi khi thay nuoc can tim. Khong go phim."""
    for _ in range(max_steps):
        el, name = _find_location_item(dlg, country)
        if el is not None:
            return el, name
        if not _scroll_list(dlg):
            break
        time.sleep(0.4)
    return None, None


def _current_country_name(dlg):
    """Doc quoc gia hien tai tu nut Location, vd 'Location Canada, Vancouver'."""
    try:
        b = _find_button(dlg, LOCPICK_AUTO_IDS, r"location")
        t = re.sub(r"^location", "", (b.window_text() or ""), flags=re.I).strip()
        return t.split(",")[0].strip()
    except Exception:
        return ""


def _random_pick_country(dlg):
    """Chon mot nuoc NGAU NHIEN (khac nuoc hien tai), KHONG go o tim kiem.
    Thu: cuon UIA -> gui phim ao (DOWN/PGDN) vao app -> lay gi co do."""
    exclude = _current_country_name(dlg)

    def _pool():
        return [it for it in _collect_country_items(get_dialog())
                if it[1] != exclude]

    # 1) thu cuon UIA (vai app ho tro)
    for _ in range(random.randint(1, 10)):
        if not _scroll_list(dlg):
            break
        time.sleep(0.4)
    items = _pool()
    if items:
        return random.choice(items)

    # 2) gui phim ao xuong cho list doi noi dung
    #    (phim 'injected' di qua duoc; phim cua nguoi dung dang bi chan)
    for pattern in ("{DOWN}", "{PGDN}"):
        for _ in range(random.randint(2, 6)):
            try:
                dlg.type_keys(pattern, pause=0.04)
            except Exception:
                pass
            time.sleep(0.5)
            items = _pool()
            if items:
                return random.choice(items)

    # 3) con gi lay do (it nhat van khac nuoc hien tai)
    items = _pool()
    if items:
        return random.choice(items)
    return None, None


def _resolve_country(keyword):
    """Giai ten tat/alias -> ten quoc gia day du trong HMA."""
    k = keyword.strip().lower()
    if k in ("random", "ngau nhien", "rand"):
        return random.choice(COUNTRIES), True
    if k in ALIASES:
        return ALIASES[k], False
    # neu nhap khop tuyet doi mot nuoc trong danh sach thi giu nguyen
    for c in COUNTRIES:
        if c.lower() == k:
            return c, False
    return keyword, False


def _find_location_item(dlg, keyword):
    """Tim muc quoc gia trong man hinh chon location.
    Uu tien: khop TUYET DOI -> bat dau bang keyword -> chua keyword.
    (tranh go 'uk' chon nham 'Ukraine')"""
    kw = keyword.lower()
    exact, prefix, partial, text_hit = None, None, None, None
    for ctype in ("Button", "ListItem", "TabItem", "TreeItem", "Custom", "Text"):
        try:
            els = dlg.descendants(control_type=ctype)
        except Exception:
            continue
        for e in els:
            try:
                name = (e.window_text() or "").strip()
            except Exception:
                continue
            if not name or kw not in name.lower():
                continue
            lname = name.lower()
            try:
                if e.automation_id() in LOCPICK_AUTO_IDS:
                    continue
            except Exception:
                pass
            cand = (e, name, ctype)
            if lname == kw:
                if ctype != "Text":
                    return e, name
                exact = exact or cand
            elif lname.startswith(kw) and ctype != "Text":
                prefix = prefix or cand
            elif ctype != "Text":
                partial = partial or cand
            else:
                text_hit = text_hit or cand
    cand = exact or prefix or partial
    if cand:
        return cand[0], cand[1]
    if text_hit:                       # chi la Text -> bam vao phan tu cha
        e, name, _ = text_hit
        cur = e
        for _ in range(6):
            try:
                cur = cur.parent()
                if cur.element_info.control_type in ("Button", "ListItem", "Custom", "Pane"):
                    return cur, name
            except Exception:
                break
        return e, name
    return None, None


def switch_country(keyword):
    """Doi sang quoc gia khac. Ho tro keyword 'random'.
    UU TIEN: cuon danh sach A-Z roi bam truc tiep (khong go phim gi ca).
    O tim kiem chi la phuong an du phong cuoi cung."""
    country, is_random = _resolve_country(keyword)

    guard = _FocusGuard()              # linh gac focus
    kblock = _KeyboardBlock()          # chi bat NEU buoc phai go vao o tim kiem
    guard.start()
    try:
        old_ip = public_ip()

        def _focus_back():
            if guard._user_hwnd:
                _restore_foreground(guard._user_hwnd)

        # Chan go phim cua nguoi dung trong luc chon nuoc
        # (app hay giat focus; phim injected cua script van di qua binh thuong)
        kblock.start()
        _open_location_picker(get_dialog())
        _focus_back()

        # ---- Chon KHONG can go vao o tim kiem ----
        el, name = None, None
        if is_random:
            el, name = _random_pick_country(get_dialog())
            if name:
                print("Quoc gia ngau nhien:", name)
                country = name
        else:
            print("Dang cuon danh sach tim:", country)
            el, name = _scroll_find_country(get_dialog(), country)
            if el is None:
                # go tam vao o tim kiem (phim cua ban dang bi chan)
                print("Cuon khong thay -> tam dung o tim kiem:", country)
                try:
                    edits = get_dialog().descendants(control_type="Edit")
                except Exception:
                    edits = []
                if edits:
                    _set_edit_text(edits[0], country)
                    time.sleep(1.8)
                el, name = _find_location_item(get_dialog(), country)

        if el is None:
            print(f"Khong tim thay quoc gia nao khop '{country}'.")
            print("Chay: python hma_app_switcher.py debugloc  roi gui toi ket qua.")
            return None
        print("Chon:", name)
        _press(el)
        _focus_back()
        time.sleep(1)

        # Nuoc co nhieu thanh pho (nut mo rong) -> tu chon thanh pho dau tien
        for sep in (",", " -"):
            sub, subname = _find_location_item(get_dialog(), country + sep)
            if sub is not None:
                print("Chon thanh pho:", subname)
                _press(sub)
                _focus_back()
                break

        _confirm_disconnect_continue()          # neu app hoi thi tu bam
        _focus_back()
        kblock.stop()
        time.sleep(2)

        # Doi nuoc co the lam VPN tat; dam bao ON lai, bo qua loi tam thoi
        try:
            if not _is_on(_switch_button_retry(timeout=15)):
                print("Dam bao VPN dang bat...")
                _ensure_vpn_on()
        except Exception:
            pass

        new_ip = _wait_new_ip(old_ip)
        if new_ip:
            print("IP cu :", old_ip)
            print("IP moi:", new_ip)
            return new_ip
        print("IP hien tai:", public_ip(), "(doi xac nhan tren app hoac thu lai)")
        return None
    finally:
        kblock.stop()                           # chac chan tra lai ban phim
        guard.stop()


def _debug_location_screen():
    dlg = get_dialog()
    _open_location_picker(dlg)
    dlg = get_dialog()
    print("--- Man hinh chon location: tat ca phan tu co ten ---")
    for ctype in ("Edit", "Button", "ListItem", "Custom", "Text", "Pane"):
        try:
            els = dlg.descendants(control_type=ctype)
        except Exception:
            continue
        for e in els:
            try:
                name = (e.window_text() or "").strip()
            except Exception:
                continue
            if name:
                print(f"  [{ctype}] name={name!r}   auto_id={e.automation_id()!r}")


def debug():
    dlg = get_dialog()
    print("Cua so dang dieu khien:", repr(dlg.window_text()),
          "| class:", dlg.class_name())
    print("\n--- Cac nut (Button) ---")
    for b in dlg.descendants(control_type="Button"):
        print(f"  [Button] name={b.window_text()!r}   auto_id={b.automation_id()!r}")
    print("\n--- Cac Text/TextBox ---")
    for t in dlg.descendants(control_type="Text"):
        print(f"  [Text] name={t.window_text()!r}   auto_id={t.automation_id()!r}")


if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "status"
    if cmd == "country":
        if len(sys.argv) < 3:
            print('Dung: python hma_app_switcher.py country "USA"  (hoac "random")')
        else:
            switch_country(sys.argv[2])
    elif cmd == "randomcountry":
        switch_country("random")
    elif cmd == "countries":
        print(f"{len(COUNTRIES)} quoc gia ho tro random:")
        for c in COUNTRIES:
            print("  -", c)
    elif cmd == "debugloc":
        _debug_location_screen()
    else:
        {"status": status, "connect": connect, "switch": switch_ip,
         "debug": debug}.get(cmd, lambda: print(__doc__))()
