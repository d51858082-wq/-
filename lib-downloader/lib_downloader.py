# -*- coding: utf-8 -*-
"""
Lib Downloader — манга -> PDF (Mangalib / Hentailib) и аниме-серии (AnimeLib)
Сделано для Алексея. Windows 10.

Установка:   pip install requests pillow
Запуск:      python lib_downloader.py
Только для личного офлайн-просмотра/чтения.
"""
import io
import json
import queue
import random
import re
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import requests
from PIL import Image, ImageTk

API = "https://api.cdnlibs.org/api"
IMG_BASE = "https://img2.imglib.info"      # если картинки манги не грузятся -> https://img3.mixlib.me
VIDEO_BASE = "https://video1.anilib.me"    # на случай относительных ссылок на видео
SITES = {
    "mangalib": {"id": "1", "ref": "https://mangalib.me/"},
    "hentailib": {"id": "4", "ref": "https://hentailib.me/"},
    "anilib": {"id": "5", "ref": "https://anilib.me/"},
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ---------- тема ----------
BG = "#1e1b2e"
PANEL = "#2a2640"
FIELD = "#352f52"
ACCENT = "#ff7eb6"
ACCENT2 = "#8ecbff"
TEXT = "#f3e9ff"


# ======================= логика загрузки =======================
def safe_name(s) -> str:
    return re.sub(r'[<>:"/\\|?*\n\r\t]', "_", str(s)).strip(" .")[:120] or "untitled"


def parse_url(url: str):
    low = url.lower()
    if "anilib" in low or "animelib" in low:
        site = "anilib"
    elif "hentailib" in low:
        site = "hentailib"
    else:
        site = "mangalib"
    m = re.search(r"(\d+--[\w\-]+)", url)
    if not m:
        raise ValueError(f"Не удалось найти slug в ссылке: {url}")
    return m.group(1), site


def parse_token(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith("{"):
        try:
            return json.loads(raw).get("token", {}).get("access_token", "")
        except Exception:
            return ""
    return raw.replace("Bearer ", "")


def make_session(site: str, token: str = "") -> requests.Session:
    s = requests.Session()
    cfg = SITES[site]
    s.headers.update({
        "User-Agent": UA,
        "Site-Id": cfg["id"],
        "Referer": cfg["ref"],
        "Origin": cfg["ref"].rstrip("/"),
        "Accept": "application/json, image/*, */*",
    })
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def http_get(sess, url, params=None, retries=5):
    last = None
    for i in range(retries):
        try:
            r = sess.get(url, params=params, timeout=40)
            if r.status_code == 429:
                time.sleep(3 * (i + 1))
                last = Exception("429 Too Many Requests")
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def fnum(x):
    try:
        return float(x)
    except Exception:
        return 0.0


# ---------- манга ----------
def page_url(u: str) -> str:
    if u.startswith("http"):
        return u
    return IMG_BASE + "/" + u.lstrip("/")


def build_pdf(images, out: Path):
    pil = []
    for data in images:
        im = Image.open(io.BytesIO(data))
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        pil.append(im)
    if not pil:
        return
    tmp = out.with_suffix(".tmp")
    pil[0].save(tmp, "PDF", save_all=True, append_images=pil[1:], resolution=100.0)
    tmp.replace(out)


def download_manga(url, cfg, log, stop):
    slug, site = parse_url(url)
    s = make_session(site, cfg["token"])
    info = http_get(s, f"{API}/manga/{slug}").json()["data"]
    title = safe_name(info.get("rus_name") or info.get("name") or slug)
    log(f"▶ {title}")

    chapters = http_get(s, f"{API}/manga/{slug}/chapters").json()["data"]
    seen, uniq = set(), []
    for ch in chapters:
        key = (str(ch.get("volume")), str(ch.get("number")))
        if key not in seen:
            seen.add(key)
            uniq.append(ch)
    uniq.sort(key=lambda c: (fnum(c.get("volume")), fnum(c.get("number"))))
    log(f"  {title}: глав найдено — {len(uniq)}")

    out_dir = Path(cfg["folder"]) / title
    out_dir.mkdir(parents=True, exist_ok=True)

    units = []
    if cfg["mode"] == "volume":
        vols = {}
        for ch in uniq:
            vols.setdefault(str(ch.get("volume")), []).append(ch)
        for v, chs in vols.items():
            units.append((f"Том {v}.pdf", chs))
    else:
        for ch in uniq:
            units.append((f"Том {ch.get('volume')} Глава {ch.get('number')}.pdf", [ch]))

    for idx, (fname, chs) in enumerate(units, 1):
        if stop.is_set():
            log(f"  {title}: остановлено")
            return
        out = out_dir / safe_name(fname)
        if out.exists():
            continue
        urls = []
        for ch in chs:
            data = http_get(
                s, f"{API}/manga/{slug}/chapter",
                params={"number": ch.get("number"), "volume": ch.get("volume")},
            ).json()["data"]
            urls += [page_url(p["url"]) for p in data.get("pages", [])]
        if not urls:
            log(f"  ⚠ {title}/{fname}: нет страниц (нужен токен для 18+?)")
            continue
        try:
            with ThreadPoolExecutor(max_workers=cfg["img_workers"]) as ex:
                images = list(ex.map(lambda u: http_get(s, u).content, urls))
            build_pdf(images, out)
            log(f"  ✓ {title}: {fname}  ({idx}/{len(units)})")
        except Exception as e:
            log(f"  ✗ {title}/{fname}: {e}")
    log(f"■ Готово: {title}")


# ---------- аниме ----------
def pick_video(detail, target_q):
    for p in detail.get("players", []):
        if p.get("player") != "Animelib" or not p.get("video"):
            continue
        qs = p["video"].get("quality") or []
        cands = sorted((int(q.get("quality") or 0), q.get("href")) for q in qs if q.get("href"))
        if not cands:
            continue
        ok = [c for c in cands if c[0] <= target_q]
        q, href = ok[-1] if ok else cands[0]
        team = (p.get("team") or {}).get("name", "")
        return q, href, team
    return None


def norm_video_url(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return VIDEO_BASE + href
    return href


def download_file(sess, url, out: Path, stop):
    tmp = out.with_suffix(".part")
    done = tmp.stat().st_size if tmp.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with sess.get(url, headers=headers, stream=True, timeout=40) as r:
        if r.status_code == 416:
            tmp.replace(out)
            return True
        r.raise_for_status()
        mode = "ab" if r.status_code == 206 else "wb"
        with open(tmp, mode) as f:
            for chunk in r.iter_content(1 << 20):
                if stop.is_set():
                    return False
                f.write(chunk)
    tmp.replace(out)
    return True


def download_anime(url, cfg, log, stop):
    slug, site = parse_url(url)
    s = make_session(site, cfg["token"])
    info = http_get(s, f"{API}/anime/{slug}").json()["data"]
    title = safe_name(info.get("rus_name") or info.get("name") or slug)
    log(f"▶ {title}")

    eps = http_get(s, f"{API}/episodes", params={"anime_id": slug}).json()["data"]
    eps.sort(key=lambda e: (fnum(e.get("season")), fnum(e.get("item_number"))))
    log(f"  {title}: серий найдено — {len(eps)}")

    out_dir = Path(cfg["folder"]) / title
    out_dir.mkdir(parents=True, exist_ok=True)

    # для видео отдельная сессия без токена (чтобы не светить его на CDN)
    vs = requests.Session()
    vs.headers.update({"User-Agent": UA, "Referer": SITES[site]["ref"]})

    def one(ep):
        if stop.is_set():
            return
        num = ep.get("item_number")
        season = ep.get("season") or "1"
        try:
            detail = http_get(s, f"{API}/episodes/{ep['id']}").json()["data"]
            picked = pick_video(detail, cfg["quality"])
            if not picked:
                log(f"  ⚠ {title}: серия {num} — нет плеера Animelib (только внешние плееры)")
                return
            q, href, team = picked
            name = f"{title} - s{season}e{str(num).zfill(2)} [{q}p].mp4"
            out = out_dir / safe_name(name)
            if out.exists():
                return
            if download_file(vs, norm_video_url(href), out, stop):
                log(f"  ✓ {title}: серия {num} ({q}p{', ' + team if team else ''})")
        except Exception as e:
            log(f"  ✗ {title}: серия {num}: {e}")

    with ThreadPoolExecutor(max_workers=min(3, cfg["img_workers"])) as ex:
        list(ex.map(one, eps))
    log(f"■ Готово: {title}")


def download_title(url, cfg, log, stop):
    _, site = parse_url(url)
    if site == "anilib":
        download_anime(url, cfg, log, stop)
    else:
        download_manga(url, cfg, log, stop)


# ======================= интерфейс =======================
W, H = 250, 680


def draw_girl(c, cx, cy, s, hair, eye, dress, bow):
    """Оригинальная чиби-девочка, нарисованная примитивами."""
    def R(x1, y1, x2, y2):
        return cx + x1 * s, cy + y1 * s, cx + x2 * s, cy + y2 * s

    # хвостики и задние волосы
    c.create_oval(*R(-100, -10, -50, 100), fill=hair, outline="")
    c.create_oval(*R(50, -10, 100, 100), fill=hair, outline="")
    c.create_oval(*R(-64, -78, 64, 62), fill=hair, outline="")
    # платье
    c.create_polygon(cx - 34 * s, cy + 80 * s, cx + 34 * s, cy + 80 * s,
                     cx + 58 * s, cy + 150 * s, cx - 58 * s, cy + 150 * s,
                     fill=dress, outline="")
    c.create_oval(*R(-10, 84, 10, 100), fill="#ffffff", outline="")
    # лицо
    c.create_oval(*R(-50, -48, 50, 58), fill="#ffe3d3", outline="")
    # чёлка
    pts = [-54, -8, -50, -56, 0, -76, 50, -56, 54, -8, 32, -36, 12, -14, -8, -40, -30, -14]
    c.create_polygon([cx + v * s if i % 2 == 0 else cy + v * s for i, v in enumerate(pts)],
                     fill=hair, outline="")
    # глаза
    for dx in (-24, 24):
        ex = cx + dx * s
        c.create_oval(ex - 13 * s, cy + 0 * s, ex + 13 * s, cy + 38 * s, fill="white", outline="#4a3a5a")
        c.create_oval(ex - 10 * s, cy + 5 * s, ex + 10 * s, cy + 38 * s, fill=eye, outline="")
        c.create_oval(ex - 5 * s, cy + 14 * s, ex + 5 * s, cy + 31 * s, fill="#1b1030", outline="")
        c.create_oval(ex - 8 * s, cy + 7 * s, ex - 1 * s, cy + 16 * s, fill="white", outline="")
    # румянец и рот
    for dx in (-34, 34):
        c.create_oval(cx + (dx - 9) * s, cy + 40 * s, cx + (dx + 9) * s, cy + 50 * s, fill="#ffb3c1", outline="")
    c.create_arc(cx - 8 * s, cy + 38 * s, cx + 8 * s, cy + 52 * s, start=200, extent=140,
                 style="arc", outline="#c2506a", width=2)
    # бантик
    bx, by = cx - 42 * s, cy - 54 * s
    c.create_polygon(bx, by, bx - 22 * s, by - 14 * s, bx - 22 * s, by + 14 * s, fill=bow, outline="")
    c.create_polygon(bx, by, bx + 22 * s, by - 14 * s, bx + 22 * s, by + 14 * s, fill=bow, outline="")
    c.create_oval(bx - 5 * s, by - 5 * s, bx + 5 * s, by + 5 * s, fill="#ffffff", outline="")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("✿ Lib Downloader ✿")
        self.geometry("1020x700")
        self.minsize(900, 640)
        self.configure(bg=BG)
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.bg_img = None
        self.petals = []

        self.folder = tk.StringVar(value=str(Path.home() / "Downloads" / "LibDownloader"))
        self.mode = tk.StringVar(value="chapter")
        self.quality = tk.StringVar(value="1080")
        self.title_workers = tk.IntVar(value=2)
        self.img_workers = tk.IntVar(value=6)

        self.style_setup()

        # левая панель с девочками
        self.art = tk.Canvas(self, width=W, height=H, bg=PANEL, highlightthickness=0)
        self.art.pack(side="left", fill="y")
        self.redraw_art()
        self.animate()

        # правая часть
        f = ttk.Frame(self, padding=14)
        f.pack(side="left", fill="both", expand=True)

        ttk.Label(f, text="✿ Lib Downloader ✿", style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text="Привет, Алексей! Вставь ссылки — манга станет PDF, аниме — mp4.",
                  style="Sub.TLabel").pack(anchor="w", pady=(0, 10))

        ttk.Label(f, text="Ссылки на тайтлы (Mangalib / Hentailib / AnimeLib), по одной в строке:").pack(anchor="w")
        self.urls = scrolledtext.ScrolledText(f, height=7, bg=FIELD, fg=TEXT, insertbackground=ACCENT,
                                              relief="flat", font=("Consolas", 10), bd=6)
        self.urls.pack(fill="x", pady=(2, 8))

        ttk.Label(f, text="Токен (для 18+; можно вставить всё значение ключа 'auth'):").pack(anchor="w")
        self.token = ttk.Entry(f, show="•")
        self.token.pack(fill="x", pady=(2, 8))

        row = ttk.Frame(f)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Папка:").pack(side="left")
        ttk.Entry(row, textvariable=self.folder).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Выбрать", command=self.pick_folder).pack(side="left")

        opt = ttk.LabelFrame(f, text=" Настройки ", padding=8)
        opt.pack(fill="x", pady=(0, 8))
        ttk.Radiobutton(opt, text="Манга: 1 глава = 1 PDF", variable=self.mode, value="chapter").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(opt, text="1 том = 1 PDF", variable=self.mode, value="volume").grid(row=0, column=1, sticky="w", padx=10)
        ttk.Label(opt, text="Аниме, качество:").grid(row=0, column=2, padx=(20, 4))
        ttk.Combobox(opt, textvariable=self.quality, values=["1080", "720", "480", "360"],
                     width=6, state="readonly").grid(row=0, column=3)
        ttk.Label(opt, text="Тайтлов одновременно:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(opt, from_=1, to=8, width=4, textvariable=self.title_workers).grid(row=1, column=1, sticky="w", padx=10, pady=(8, 0))
        ttk.Label(opt, text="Потоков внутри тайтла:").grid(row=1, column=2, pady=(8, 0), padx=(20, 4))
        ttk.Spinbox(opt, from_=1, to=16, width=4, textvariable=self.img_workers).grid(row=1, column=3, pady=(8, 0))

        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=(0, 6))
        self.start_btn = ttk.Button(btns, text="♡ Скачать", style="Accent.TButton", command=self.start)
        self.start_btn.pack(side="left")
        ttk.Button(btns, text="Стоп", command=self.stop.set).pack(side="left", padx=6)
        ttk.Button(btns, text="Своя арт-картинка…", command=self.pick_art).pack(side="left", padx=6)
        ttk.Button(btns, text="Сбросить арт", command=self.reset_art).pack(side="left")

        self.bar = ttk.Progressbar(f, mode="indeterminate")
        self.bar.pack(fill="x", pady=(0, 6))

        self.logbox = scrolledtext.ScrolledText(f, state="disabled", height=10, bg=FIELD, fg=TEXT,
                                                relief="flat", font=("Consolas", 9), bd=6)
        self.logbox.pack(fill="both", expand=True)
        self.after(100, self.poll)

    # ---- стиль ----
    def style_setup(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, font=("Segoe UI", 10))
        st.configure("TFrame", background=BG)
        st.configure("TLabel", background=BG, foreground=TEXT)
        st.configure("Title.TLabel", font=("Segoe UI", 22, "bold"), foreground=ACCENT)
        st.configure("Sub.TLabel", foreground=ACCENT2)
        st.configure("TLabelframe", background=BG, foreground=ACCENT, bordercolor=FIELD)
        st.configure("TLabelframe.Label", background=BG, foreground=ACCENT)
        st.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=ACCENT, padding=5)
        st.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT, arrowcolor=ACCENT)
        st.configure("TCombobox", fieldbackground=FIELD, foreground=TEXT, arrowcolor=ACCENT)
        st.configure("TRadiobutton", background=BG, foreground=TEXT)
        st.map("TRadiobutton", background=[("active", BG)], foreground=[("active", ACCENT)])
        st.configure("TButton", background=PANEL, foreground=TEXT, padding=(12, 6), borderwidth=0)
        st.map("TButton", background=[("active", FIELD)])
        st.configure("Accent.TButton", background=ACCENT, foreground="#2b1030", font=("Segoe UI", 10, "bold"))
        st.map("Accent.TButton", background=[("active", "#ff9cc9"), ("disabled", "#6b4a5e")])
        st.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD, borderwidth=0)

    # ---- арт ----
    def redraw_art(self):
        c = self.art
        c.delete("all")
        self.petals = []
        if self.bg_img:
            c.create_image(0, 0, image=self.bg_img, anchor="nw")
        else:
            for i in range(0, H, 4):  # лёгкий градиент
                t = i / H
                r = int(0x2a + (0x4a - 0x2a) * t)
                g = int(0x26 + (0x2a - 0x26) * t)
                b = int(0x40 + (0x6a - 0x40) * t)
                c.create_rectangle(0, i, W, i + 4, fill=f"#{r:02x}{g:02x}{b:02x}", outline="")
            draw_girl(c, 128, 130, 0.95, "#ff9ccf", "#6a5cff", "#ffffff", "#7ad3ff")
            draw_girl(c, 122, 420, 0.95, "#8fd0ff", "#ff6a9a", "#ffe0f0", "#ff7eb6")
            c.create_text(W // 2, 40 + 0, text="", fill=TEXT)
            c.create_text(W // 2, 662, text="♡ ganbare! ♡", fill=ACCENT, font=("Segoe UI", 12, "bold"))
        for _ in range(14):
            x, y = random.randint(0, W), random.randint(-H, H)
            pid = c.create_oval(x, y, x + 8, y + 6, fill="#ffc2dc", outline="")
            self.petals.append([pid, random.uniform(0.8, 2.2), random.uniform(-0.6, 0.6)])

    def animate(self):
        for p in self.petals:
            self.art.move(p[0], p[2], p[1])
            x1, y1, x2, y2 = self.art.coords(p[0])
            if y1 > H:
                self.art.move(p[0], random.randint(-W // 2, W // 2) - x1, -H - 20)
            elif x1 > W + 10:
                self.art.move(p[0], -W - 20, 0)
            elif x2 < -10:
                self.art.move(p[0], W + 20, 0)
        self.after(50, self.animate)

    def pick_art(self):
        path = filedialog.askopenfilename(filetypes=[("Картинки", "*.png *.jpg *.jpeg *.webp")])
        if not path:
            return
        try:
            im = Image.open(path).convert("RGB")
            scale = max(W / im.width, H / im.height)
            im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
            left, top = (im.width - W) // 2, (im.height - H) // 2
            im = im.crop((left, top, left + W, top + H))
            self.bg_img = ImageTk.PhotoImage(im)
            self.redraw_art()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def reset_art(self):
        self.bg_img = None
        self.redraw_art()

    # ---- действия ----
    def pick_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.folder.set(d)

    def log(self, msg):
        self.q.put(msg)

    def poll(self):
        while not self.q.empty():
            m = self.q.get()
            self.logbox.configure(state="normal")
            self.logbox.insert("end", m + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        self.after(100, self.poll)

    def start(self):
        links = [l.strip() for l in self.urls.get("1.0", "end").splitlines() if l.strip()]
        if not links:
            messagebox.showwarning("Пусто", "Вставь хотя бы одну ссылку")
            return
        cfg = {
            "folder": self.folder.get(),
            "mode": self.mode.get(),
            "quality": int(self.quality.get()),
            "token": parse_token(self.token.get()),
            "img_workers": max(1, self.img_workers.get()),
        }
        self.stop.clear()
        self.start_btn.configure(state="disabled")
        self.bar.start(12)
        threading.Thread(target=self.run, args=(links, cfg), daemon=True).start()

    def run(self, links, cfg):
        def job(u):
            try:
                download_title(u, cfg, self.log, self.stop)
            except Exception as e:
                self.log(f"✗ {u}: {e}")

        with ThreadPoolExecutor(max_workers=max(1, self.title_workers.get())) as ex:
            list(ex.map(job, links))
        self.log("=== Всё завершено ♡ ===")
        self.after(0, self.finish)

    def finish(self):
        self.bar.stop()
        self.start_btn.configure(state="normal")


if __name__ == "__main__":
    App().mainloop()
