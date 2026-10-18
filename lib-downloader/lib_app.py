# -*- coding: utf-8 -*-
"""
Lib App — вход по логину/паролю, поиск тайтлов, очередь и загрузка.
Для Алексея. Положи этот файл В ТУ ЖЕ ПАПКУ, где лежит lib_downloader.py.

Запуск:  python lib_app.py
"""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk, scrolledtext, filedialog

import requests

from lib_downloader import (
    API, SITES, UA, BG, PANEL, FIELD, ACCENT, ACCENT2, TEXT, W, H,
    App, make_session, http_get, parse_url, parse_token, download_title,
)

CFG_PATH = Path.home() / ".lib_downloader.json"   # хранится только токен, пароль НЕ сохраняется
URL_TEMPLATES = {
    "mangalib": "https://mangalib.me/ru/manga/{slug}",
    "hentailib": "https://hentailib.me/ru/manga/{slug}",
    "anilib": "https://anilib.me/ru/anime/{slug}",
}
SECTIONS = {"Манга (Mangalib)": "mangalib", "18+ (Hentailib)": "hentailib", "Аниме (AnimeLib)": "anilib"}


def load_cfg():
    try:
        return json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(d):
    try:
        CFG_PATH.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def find_token(o):
    if isinstance(o, dict):
        if isinstance(o.get("access_token"), str):
            return o["access_token"]
        for v in o.values():
            t = find_token(v)
            if t:
                return t
    elif isinstance(o, list):
        for v in o:
            t = find_token(v)
            if t:
                return t
    return ""


def api_login(email, password):
    """Пробуем несколько известных вариантов входа. Может не сработать, если сайт требует капчу/2FA."""
    headers = {
        "User-Agent": UA, "Site-Id": "1", "Content-Type": "application/json",
        "Referer": SITES["mangalib"]["ref"], "Origin": SITES["mangalib"]["ref"].rstrip("/"),
    }
    attempts = [
        (f"{API}/auth/oauth/token",
         {"grant_type": "password", "client_id": "1", "username": email, "password": password, "scope": ""}),
        (f"{API}/auth/login", {"email": email, "password": password, "remember": True}),
    ]
    last = "неизвестная ошибка"
    for url, body in attempts:
        try:
            r = requests.post(url, json=body, headers=headers, timeout=30)
        except requests.RequestException as e:
            last = str(e)
            continue
        if r.ok:
            try:
                tok = find_token(r.json())
            except Exception:
                tok = ""
            if tok:
                return tok
            last = "в ответе нет токена"
        else:
            last = f"HTTP {r.status_code}"
    raise RuntimeError(last)


def whoami(token):
    s = make_session("mangalib", token)
    data = http_get(s, f"{API}/auth/me", retries=2).json().get("data", {})
    return data.get("username") or data.get("name") or "user"


WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def webview_login_main(out_path):
    """Отдельный процесс: окно с настоящим сайтом, где можно войти через VK/Google/и т.д.
    Как только на сайте появляется токен, записываем его в файл и закрываем окно."""
    out = Path(out_path)
    try:
        import time
        import webview

        win = webview.create_window(
            "Lib — нажми «Войти» на сайте и войди любым способом (VK, Google…)",
            "https://mangalib.me/", width=1000, height=780)

        def watcher():
            end = time.time() + 900
            while time.time() < end:
                time.sleep(1.5)
                try:
                    raw = win.evaluate_js("localStorage.getItem('auth')")
                except Exception:
                    continue
                tok = parse_token(raw or "")
                if tok:
                    out.write_text(tok, encoding="utf-8")
                    try:
                        win.destroy()
                    except Exception:
                        pass
                    return

        webview.start(watcher, user_agent=UA, private_mode=False,
                      storage_path=str(Path.home() / ".lib_downloader_webview"))
    except Exception as e:
        out.write_text("ERR:" + str(e), encoding="utf-8")
    os._exit(0)


class Main(tk.Tk):
    # переиспользуем оформление и арт из lib_downloader.py
    style_setup = App.style_setup
    redraw_art = App.redraw_art
    animate = App.animate
    pick_art = App.pick_art
    reset_art = App.reset_art

    def __init__(self):
        super().__init__()
        self.title("✿ Lib App ✿")
        self.geometry("1120x800")
        self.minsize(980, 720)
        self.configure(bg=BG)
        self.uiq = queue.Queue()
        self.stop = threading.Event()
        self.bg_img = None
        self.petals = []
        self.token = ""
        self.username = ""
        self.page = 1
        self.results = {}
        self.queue_items = {}

        self.folder = tk.StringVar(value=str(Path.home() / "Downloads" / "LibDownloader"))
        self.mode = tk.StringVar(value="chapter")
        self.quality = tk.StringVar(value="1080")
        self.title_workers = tk.IntVar(value=2)
        self.img_workers = tk.IntVar(value=6)
        self.section = tk.StringVar(value=list(SECTIONS)[0])
        self.remember = tk.BooleanVar(value=True)

        self.style_setup()
        st = ttk.Style(self)
        st.configure("TCheckbutton", background=BG, foreground=TEXT)
        st.map("TCheckbutton", background=[("active", BG)], foreground=[("active", ACCENT)])
        st.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT,
                     rowheight=24, borderwidth=0)
        st.configure("Treeview.Heading", background=PANEL, foreground=ACCENT, relief="flat")
        st.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#2b1030")])

        self.art = tk.Canvas(self, width=W, height=H, bg=PANEL, highlightthickness=0)
        self.art.pack(side="left", fill="y")
        self.redraw_art()
        self.animate()

        self.holder = ttk.Frame(self, padding=14)
        self.holder.pack(side="left", fill="both", expand=True)
        self.build_login()
        self.build_main()

        self.after(100, self.poll)
        saved = load_cfg().get("token")
        if saved:
            self.show_login(busy="Проверяю сохранённый вход…")
            self.run_bg(lambda: whoami(saved), lambda name: self.enter(saved, name),
                        lambda err: self.show_login())
        else:
            self.show_login()

    # ---------- служебное ----------
    def ui(self, fn):
        self.uiq.put(fn)

    def poll(self):
        while not self.uiq.empty():
            try:
                self.uiq.get()()
            except Exception:
                pass
        self.after(100, self.poll)

    def run_bg(self, work, ok, fail):
        def target():
            try:
                res = work()
            except Exception as e:
                msg = str(e)
                self.ui(lambda: fail(msg))
                return
            self.ui(lambda: ok(res))
        threading.Thread(target=target, daemon=True).start()

    def log(self, msg):
        def w():
            self.logbox.configure(state="normal")
            self.logbox.insert("end", msg + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        self.ui(w)

    # ---------- экран входа ----------
    def build_login(self):
        self.login_frame = ttk.Frame(self.holder)
        box = ttk.Frame(self.login_frame)
        box.place(relx=0.5, rely=0.45, anchor="center")
        ttk.Label(box, text="✿ Lib App ✿", style="Title.TLabel").pack(pady=(0, 4))
        ttk.Label(box, text="Войди в свой аккаунт Lib", style="Sub.TLabel").pack(pady=(0, 16))
        ttk.Label(box, text="Логин (email)").pack(anchor="w")
        self.e_login = ttk.Entry(box, width=34)
        self.e_login.pack(pady=(2, 8))
        ttk.Label(box, text="Пароль").pack(anchor="w")
        self.e_pass = ttk.Entry(box, width=34, show="•")
        self.e_pass.pack(pady=(2, 8))
        self.e_pass.bind("<Return>", lambda e: self.do_login())
        ttk.Checkbutton(box, text="Запомнить меня (сохраняется только токен)",
                        variable=self.remember).pack(anchor="w", pady=(0, 10))
        self.login_btn = ttk.Button(box, text="♡ Войти", style="Accent.TButton", command=self.do_login)
        self.login_btn.pack(fill="x")
        self.social_btn = ttk.Button(box, text="Войти через сайт (VK / Google / …)", command=self.social_login)
        self.social_btn.pack(fill="x", pady=(8, 0))
        ttk.Button(box, text="Войти по токену…", command=self.token_login).pack(fill="x", pady=(8, 0))
        ttk.Button(box, text="Продолжить как гость (без 18+)", command=lambda: self.enter("", "гость")).pack(fill="x", pady=(8, 0))
        self.login_msg = ttk.Label(box, text="", foreground=ACCENT2, wraplength=320, justify="center")
        self.login_msg.pack(pady=(12, 0))

    def show_login(self, busy=""):
        self.main_frame.pack_forget()
        self.login_frame.pack(fill="both", expand=True)
        self.login_msg.configure(text=busy)

    def do_login(self):
        email, pwd = self.e_login.get().strip(), self.e_pass.get()
        if not email or not pwd:
            self.login_msg.configure(text="Введи логин и пароль")
            return
        self.login_btn.configure(state="disabled")
        self.login_msg.configure(text="Входим…")

        def work():
            tok = api_login(email, pwd)
            try:
                name = whoami(tok)
            except Exception:
                name = email
            return tok, name

        def ok(res):
            self.login_btn.configure(state="normal")
            self.e_pass.delete(0, "end")
            self.enter(*res)

        def fail(err):
            self.login_btn.configure(state="normal")
            self.login_msg.configure(
                text=f"Не удалось войти ({err}). Возможно, сайт просит капчу — "
                     f"тогда нажми «Войти по токену…».")

        self.run_bg(work, ok, fail)

    def social_login(self):
        self.login_btn.configure(state="disabled")
        self.social_btn.configure(state="disabled")
        self.login_msg.configure(
            text="Открылось окно сайта: нажми там «Войти» и войди любым способом "
                 "(VK, Google и т.д.). Окно закроется само.")
        out = Path(tempfile.gettempdir()) / "lib_login_token.txt"
        try:
            out.unlink()
        except Exception:
            pass
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--webview-login", str(out)]
        else:
            cmd = [sys.executable, os.path.abspath(__file__), "--webview-login", str(out)]
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")

        def work():
            subprocess.run(cmd, timeout=1000, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            txt = out.read_text(encoding="utf-8").strip() if out.exists() else ""
            try:
                out.unlink()
            except Exception:
                pass
            if txt.startswith("ERR:"):
                raise RuntimeError("не удалось открыть окно сайта. Нужен Microsoft Edge WebView2: "
                                   + WEBVIEW2_URL + " (" + txt[4:120] + ")")
            if not txt:
                raise RuntimeError("окно закрыто до входа")
            try:
                name = whoami(txt)
            except Exception:
                name = "user"
            return txt, name

        def done():
            self.login_btn.configure(state="normal")
            self.social_btn.configure(state="normal")

        def ok(res):
            done()
            self.enter(*res)

        def fail(err):
            done()
            self.login_msg.configure(text=f"Вход через сайт не удался: {err}")

        self.run_bg(work, ok, fail)

    def token_login(self):
        raw = simpledialog.askstring(
            "Токен", "Вставь токен (или всё значение ключа 'auth' из Local Storage сайта):", parent=self)
        tok = parse_token(raw or "")
        if not tok:
            return
        self.login_msg.configure(text="Проверяю токен…")
        self.run_bg(lambda: whoami(tok), lambda name: self.enter(tok, name),
                    lambda err: self.login_msg.configure(text=f"Токен не подошёл ({err})"))

    def enter(self, token, name):
        self.token, self.username = token, name
        if self.remember.get() and token:
            save_cfg({"token": token})
        self.hello.configure(text=f"Привет, {name}! Выбирай, что скачать ♡")
        self.login_frame.pack_forget()
        self.main_frame.pack(fill="both", expand=True)

    def logout(self):
        self.token = ""
        save_cfg({})
        self.show_login()

    # ---------- основной экран ----------
    def build_main(self):
        f = self.main_frame = ttk.Frame(self.holder)

        top = ttk.Frame(f)
        top.pack(fill="x")
        self.hello = ttk.Label(top, text="", style="Title.TLabel", font=("Segoe UI", 16, "bold"))
        self.hello.pack(side="left")
        ttk.Button(top, text="Выйти", command=self.logout).pack(side="right")

        sr = ttk.Frame(f)
        sr.pack(fill="x", pady=(10, 6))
        ttk.Combobox(sr, textvariable=self.section, values=list(SECTIONS), state="readonly", width=18).pack(side="left")
        self.q_entry = ttk.Entry(sr)
        self.q_entry.pack(side="left", fill="x", expand=True, padx=6)
        self.q_entry.bind("<Return>", lambda e: self.search())
        ttk.Button(sr, text="Найти", style="Accent.TButton", command=self.search).pack(side="left")

        rf = ttk.Frame(f)
        rf.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(rf, columns=("name", "info"), show="headings", selectmode="extended", height=9)
        self.tree.heading("name", text="Название")
        self.tree.heading("info", text="Тип / год")
        self.tree.column("name", width=420)
        self.tree.column("info", width=140)
        sb = ttk.Scrollbar(rf, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.add_selected())

        rb = ttk.Frame(f)
        rb.pack(fill="x", pady=6)
        ttk.Button(rb, text="Ещё результаты", command=lambda: self.search(more=True)).pack(side="left")
        ttk.Button(rb, text="В очередь ➜", style="Accent.TButton", command=self.add_selected).pack(side="left", padx=6)
        self.link_entry = ttk.Entry(rb, width=28)
        self.link_entry.pack(side="right")
        ttk.Button(rb, text="Добавить ссылку", command=self.add_link).pack(side="right", padx=6)

        ttk.Label(f, text="Очередь загрузки:").pack(anchor="w")
        qf = ttk.Frame(f)
        qf.pack(fill="x")
        self.qtree = ttk.Treeview(qf, columns=("name", "site"), show="headings", selectmode="extended", height=4)
        self.qtree.heading("name", text="Название")
        self.qtree.heading("site", text="Раздел")
        self.qtree.column("name", width=420)
        self.qtree.column("site", width=140)
        self.qtree.pack(side="left", fill="x", expand=True)
        qb = ttk.Frame(qf)
        qb.pack(side="left", padx=6)
        ttk.Button(qb, text="Убрать", command=self.remove_selected).pack(fill="x")
        ttk.Button(qb, text="Очистить", command=self.clear_queue).pack(fill="x", pady=(4, 0))

        opt = ttk.LabelFrame(f, text=" Настройки ", padding=6)
        opt.pack(fill="x", pady=8)
        ttk.Radiobutton(opt, text="Манга: глава = PDF", variable=self.mode, value="chapter").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(opt, text="том = PDF", variable=self.mode, value="volume").grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(opt, text="Аниме:").grid(row=0, column=2, padx=(14, 2))
        ttk.Combobox(opt, textvariable=self.quality, values=["1080", "720", "480", "360"], width=5, state="readonly").grid(row=0, column=3)
        ttk.Label(opt, text="Тайтлов сразу:").grid(row=0, column=4, padx=(14, 2))
        ttk.Spinbox(opt, from_=1, to=8, width=3, textvariable=self.title_workers).grid(row=0, column=5)
        ttk.Label(opt, text="Потоков:").grid(row=0, column=6, padx=(10, 2))
        ttk.Spinbox(opt, from_=1, to=16, width=3, textvariable=self.img_workers).grid(row=0, column=7)
        ttk.Entry(opt, textvariable=self.folder).grid(row=1, column=0, columnspan=6, sticky="ew", pady=(6, 0))
        ttk.Button(opt, text="Папка…", command=self.pick_folder).grid(row=1, column=6, columnspan=2, pady=(6, 0), padx=(8, 0))
        opt.columnconfigure(4, weight=1)

        bt = ttk.Frame(f)
        bt.pack(fill="x")
        self.start_btn = ttk.Button(bt, text="♡ Скачать очередь", style="Accent.TButton", command=self.start)
        self.start_btn.pack(side="left")
        ttk.Button(bt, text="Стоп", command=self.stop.set).pack(side="left", padx=6)
        ttk.Button(bt, text="Своя арт-картинка…", command=self.pick_art).pack(side="left", padx=6)
        ttk.Button(bt, text="Сбросить арт", command=self.reset_art).pack(side="left")
        self.bar = ttk.Progressbar(f, mode="indeterminate")
        self.bar.pack(fill="x", pady=6)
        self.logbox = scrolledtext.ScrolledText(f, state="disabled", height=6, bg=FIELD, fg=TEXT,
                                                relief="flat", font=("Consolas", 9), bd=6)
        self.logbox.pack(fill="both", expand=False)

    def pick_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.folder.set(d)

    # ---------- поиск ----------
    def search(self, more=False):
        site = SECTIONS[self.section.get()]
        if site == "hentailib" and not self.token:
            messagebox.showinfo("18+", "Для раздела 18+ нужно войти в аккаунт.")
            return
        if more:
            self.page += 1
        else:
            self.page = 1
            self.tree.delete(*self.tree.get_children())
            self.results = {}
        q, page, token = self.q_entry.get().strip(), self.page, self.token
        path = "anime" if site == "anilib" else "manga"

        def work():
            s = make_session(site, token)
            r = http_get(s, f"{API}/{path}", params={"q": q, "site_id[]": SITES[site]["id"], "page": page})
            return r.json().get("data", [])

        def ok(data):
            if not data:
                self.log("Ничего не найдено" if page == 1 else "Больше результатов нет")
            for it in data:
                slug = it.get("slug_url")
                if not slug:
                    continue
                name = it.get("rus_name") or it.get("name") or slug
                info = " · ".join(x for x in [(it.get("type") or {}).get("label"),
                                              it.get("releaseDateString")] if x)
                iid = f"{site}:{slug}"
                if iid in self.results:
                    continue
                self.results[iid] = (site, slug, name)
                self.tree.insert("", "end", iid=iid, values=(name, info))

        self.run_bg(work, ok, lambda err: self.log(f"Поиск не удался: {err} (если 401 — войди заново)"))

    # ---------- очередь ----------
    def add_selected(self):
        for iid in self.tree.selection():
            self.queue_add(iid, *self.results[iid])

    def queue_add(self, iid, site, slug, name):
        if iid in self.queue_items:
            return
        self.queue_items[iid] = (site, slug, name)
        label = {v: k for k, v in SECTIONS.items()}[site]
        self.qtree.insert("", "end", iid=iid, values=(name, label))

    def add_link(self):
        url = self.link_entry.get().strip()
        if not url:
            return
        try:
            slug, site = parse_url(url)
        except Exception as e:
            messagebox.showwarning("Ссылка", str(e))
            return
        self.queue_add(f"{site}:{slug}", site, slug, slug)
        self.link_entry.delete(0, "end")

    def remove_selected(self):
        for iid in self.qtree.selection():
            self.queue_items.pop(iid, None)
            self.qtree.delete(iid)

    def clear_queue(self):
        self.queue_items.clear()
        self.qtree.delete(*self.qtree.get_children())

    # ---------- загрузка ----------
    def start(self):
        if not self.queue_items:
            messagebox.showinfo("Пусто", "Добавь тайтлы в очередь")
            return
        cfg = {
            "folder": self.folder.get(), "mode": self.mode.get(),
            "quality": int(self.quality.get()), "token": self.token,
            "img_workers": max(1, self.img_workers.get()),
        }
        urls = [URL_TEMPLATES[s].format(slug=slug) for s, slug, _ in self.queue_items.values()]
        self.stop.clear()
        self.start_btn.configure(state="disabled")
        self.bar.start(12)
        workers = max(1, self.title_workers.get())

        def run():
            def job(u):
                try:
                    download_title(u, cfg, self.log, self.stop)
                except Exception as e:
                    self.log(f"✗ {u}: {e}")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(job, urls))
            self.log("=== Всё завершено ♡ ===")
            self.ui(self.finish)

        threading.Thread(target=run, daemon=True).start()

    def finish(self):
        self.bar.stop()
        self.start_btn.configure(state="normal")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--webview-login":
        webview_login_main(sys.argv[2])
    else:
        Main().mainloop()
