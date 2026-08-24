#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAP VIDEO TU ANH + AUDIO THEO TIMELINE — dung chung cho MOI video cua kenh. v2.1 (2026-08-10)

Timeline N segment (prompt + reuse) duoc map vao audio chunks bang marks.tsv, roi MOI
CHUNK scale theo dung audio that cua chunk do — khong scale toan cuc.

Map beat -> chunk theo THOI GIAN: est time cua beat vs audio that tich luy
(khong can IMAGE-PRODUCTION.md, khong can script.txt/quote).

Cach dung:
    python3 build-video.py <build_dir>                # rap 1280x720, anh tinh
    python3 build-video.py <build_dir> --motion       # them zoom nhe (Ken Burns)
    python3 build-video.py <build_dir> --resolution 1920x1080
    python3 build-video.py <build_dir> --dry-run      # in bang segment + section, khong rap
    python3 build-video.py <build_dir> --subtitles    # burn phu de tu srt/ (offset theo audio that)
    python3 build-video.py <build_dir> --merge-subs   # chi gop srt -> subs-merged.ass (test nhanh)
    python3 build-video.py <build_dir> --import-images <thu_muc> [--insert "IMG-12:ten_file"] [--yes]
                                                      # import theo thu tu mtime (thu tu gen)
                                                      # [--img-order IMG-01,IMG-02,...] de doi ten
                                                      # khi chua co audio/prompts-build.py

Cau truc can co (trong <build_dir>/):
    prompts-build.py     <- N row IMG-BEAT + REUSE_BEATS (timeline est)
    marks.tsv            <- M section + cau mo dau (ranh gioi chunk)
    audio/*.mp3          <- M file audio chunk (thoi luong THAT, 1 file = 1 section)
    images/IMG-01.jpg... <- anh gen tu prompts (tu dat ten IMG-xx, hoac import)

Gate: thieu anh => dung. Scale chunk ngoai 0.7-1.35 => canh bao giờ draft nghi ngo.
Tong segment sau scale == tong audio that (sai so <=0.15s).
"""
import re, os, sys, glob, subprocess, tempfile, shutil, random  # shutil: import_images + finally

# Allow direct execution as a file (the API launches this path as a subprocess).
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

FPS = 30
SCALE_MIN, SCALE_MAX = 0.7, 1.35

SUB_DEFAULTS = {
    "font": "Hiragino Kaku Gothic Pro",
    "fontsize": 44,
    "color": "#FFFFFF",          # màu chữ
    "outline": 3,                # độ dày viền
    "outline_color": "#000000",  # màu viền
    "shadow": 1,                 # độ dày bóng
    "bold": False,
    "position": "bottom",        # bottom | top | middle
    "margin_v": 36,
}

# font JP đã xác nhận có trên máy (fc-list)
JP_FONTS = ["Hiragino Kaku Gothic Pro", "Hiragino Maru Gothic ProN",
            "Hiragino Mincho ProN", "Hiragino Sans GB"]


def hex_to_ass(h):
    """'#FFD700' -> '&H0000D7FF' (ASS dùng thứ tự BGR, alpha 00)"""
    h = h.lstrip('#')
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def parse_sub_flags(argv):
    """Doc cac flag --sub-* thanh dict style (chi ghi de cac field co flag)."""
    flags = {}
    mapping = {
        '--sub-fontsize': 'fontsize', '--sub-color': 'color',
        '--sub-outline': 'outline', '--sub-outline-color': 'outline_color',
        '--sub-shadow': 'shadow', '--sub-position': 'position',
        '--sub-font': 'font', '--sub-margin-v': 'margin_v',
    }
    for flag, key in mapping.items():
        if flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                sys.exit(f"{flag} can kem gia tri")
            flags[key] = argv[i + 1]
    if '--sub-bold' in argv:
        flags['bold'] = True
    return flags


def load_sub_style(root, flags=None):
    """Style phụ đề: file sub-style.json trong thư mục video (nếu có) + ghi đè bằng flags CLI."""
    style = dict(SUB_DEFAULTS)
    js = os.path.join(root, 'sub-style.json')
    if os.path.isfile(js):
        try:
            import json
            saved = json.load(open(js, encoding='utf-8'))
            style.update({k: v for k, v in saved.items() if k in style})
        except Exception as e:
            print(f"  WARN: sub-style.json lỗi ({e}) — dùng mặc định")
    if flags:
        style.update(flags)
    style["fontsize"] = int(style["fontsize"])
    style["outline"] = int(style["outline"])
    style["shadow"] = int(style["shadow"])
    style["margin_v"] = int(style["margin_v"])
    return style


def sec(t):
    """'0:06-0:11' hoac '4:13-4:23' -> (start_s, end_s)"""
    a, b = t.replace('–', '-').split('-')
    def tos(p):
        pp = p.split(':')
        return int(pp[0]) * 60 + int(pp[1])
    return tos(a), tos(b)


def read_file(root, name, required=True):
    p = os.path.join(root, name)
    if not os.path.isfile(p):
        if required:
            sys.exit(f"Thieu file {name} trong {root}")
        return None
    with open(p, encoding='utf-8') as fh:
        return fh.read()


def beat_key(b):
    """Sort key cho beat id: B1 < B1a < B2 (ho tro Bxx va Bxxa/Bxxb)."""
    m = re.match(r'B(\d+)(\w*)', b or '')
    return (int(m.group(1)), m.group(2)) if m else (0, b or '')


def parse_segments(root):
    """N row + M reuse -> [(img, est_start, est_end)] sap xep theo thoi gian.
    Ho tro beat id dang B01 va B01a/B01b (video 5+)."""
    src = read_file(root, 'prompts-build.py')
    rows = re.findall(r'\("(IMG-\d+)","(B\d+\w*)","([\d:–-]+)",\d+', src)
    if not rows:
        sys.exit(f"Khong doc duoc row nao tu prompts-build.py trong {root}")
    by_beat = {r[1]: r for r in rows}
    segs = []
    for r in rows:
        s, e = sec(r[2])
        segs.append((r[0], r[1], s, e))
    reuse = re.search(r'REUSE_BEATS\s*=\s*\{([^}]*)\}', src)
    if reuse:
        reuse_items = re.findall(r'"B(\d+\w*)":\s*"(IMG-\d+)"', reuse.group(1))
        all_beats = sorted(set([r[1] for r in rows] + [f"B{bn}" for bn, _ in reuse_items]),
                           key=beat_key)
        for bn, img in reuse_items:
            bid = f"B{bn}"
            idx = all_beats.index(bid)
            prev_b = next((b for b in reversed(all_beats[:idx]) if b in by_beat), None)
            next_b = next((b for b in all_beats[idx + 1:] if b in by_beat), None)
            if not prev_b or not next_b:
                sys.exit(f"REUSE {bid} thieu beat lan can co row — cap nhat tool")
            segs.append((img, bid, sec(by_beat[prev_b][2])[1], sec(by_beat[next_b][2])[0]))
    segs.sort(key=lambda x: (x[2], x[1]))
    for k in range(1, len(segs)):
        if abs(segs[k][2] - segs[k-1][3]) > 0.01:
            sys.exit(f"Timeline gap tai segment {k}: {segs[k-1]} -> {segs[k]}")
    return segs, by_beat


def parse_marks(root):
    marks = []
    for ln, line in enumerate(read_file(root, 'marks.tsv').split('\n'), 1):
        line = line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if '\t' not in line:
            sys.exit(f"marks.tsv dong {ln}: thieu TAB giua ten va cau mo dau")
        name, text = line.split('\t', 1)
        marks.append((name.strip(), text.strip()))
    if len(marks) < 2:
        sys.exit("marks.tsv can it nhat 2 section")
    return marks


def map_beats_to_chunks_by_time(segs, real_chunks):
    """Map beat -> chunk bang est time vs audio that tich luy.
    Dung cho video khong co IMAGE-PRODUCTION.md — khong can quote trong script.
    Yeu cau: est time cua moi chunk xap xi audio that (sai so nho — buoc scale sau se chinh)."""
    cum = []
    acc = 0.0
    for d in real_chunks:
        acc += d
        cum.append(acc)
    result = {}
    for img, b, s, e in segs:
        t = (s + e) / 2.0
        c = 0
        for k, cu in enumerate(cum):
            if t < cu:
                c = k
                break
        else:
            c = len(cum) - 1
        result[b] = c
    return result


def audio_files_and_total(root):
    files = sorted(glob.glob(os.path.join(root, 'audio', '*.mp3')))
    if not files:
        sys.exit(f"Khong thay file audio trong {root}/audio/")
    total = 0.0
    for f in files:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'csv=p=0', f], capture_output=True, text=True)
        total += float(r.stdout.strip())
    if len(files) != len(parse_marks(root)):
        print(f"  WARN: {len(files)} file audio nhung {len(parse_marks(root))} section trong marks.tsv")
    return files, total


def find_image(root, img):
    for ext in ('jpg', 'jpeg', 'png', 'webp'):
        p = os.path.join(root, 'images', f"{img}.{ext}")
        if os.path.isfile(p):
            return p
    return None


CLIP_EXTENSIONS = ('.mp4', '.mov', '.webm')


def find_clip(root, img):
    """Clip image-to-video user gen: video-build/clips/IMG-xx.mp4 — ưu tiên hơn ảnh."""
    for ext in CLIP_EXTENSIONS:
        p = os.path.join(root, 'clips', f"{img}{ext}")
        if os.path.isfile(p):
            return p
    return None


def canonical_img_order(root):
    """IMG id theo thu tu beat (bo id chi xuat hien trong REUSE_BEATS)."""
    src = read_file(root, 'prompts-build.py')
    rows = re.findall(r'\("(IMG-\d+)","(B\d+\w*)","([\d:–-]+)",\d+', src)
    rows.sort(key=lambda r: beat_key(r[1]))
    seen, order = set(), []
    for img, b, t in rows:
        if img not in seen:
            seen.add(img)
            order.append(img)
    return order


_IMG_ORDER_RE = re.compile(r"(?:^|[ _.\-])0*(\d{1,3})(?:[ _.\-]|$)")
_TIMESTAMP_RE = re.compile(r"_(\d{12})(?:_|\.|$)")


def _file_ctime(f):
    """Thời gian tạo file: st_birthtime (macOS/BSD) nếu có, không thì st_mtime.
    Finder sort "Date Created" dùng birthtime — cần khớp để ảnh vào đúng thứ tự."""
    st = os.stat(f)
    return getattr(st, "st_birthtime", st.st_mtime)


def _img_sort_key(f, all_have_order):
    """Thứ tự ảnh cho import:
    1) Số thứ tự rời trong tên (VD `01_...`, `gen_02.jpg` — chính xác 100%).
    2) Timestamp 12 chữ số trong tên (VD `..._202608101634_clean.jpg`).
    3) Thời gian tạo file — st_birthtime (macOS Date Created) ưu tiên hơn
       st_mtime vì copy/download giữ nguyên mtime gốc còn birthtime phản ánh
       đúng thứ tự người dùng đặt vào thư mục.
    Tie-break cuối theo tên (deterministic)."""
    base = os.path.basename(f)
    if all_have_order:
        m = _IMG_ORDER_RE.search(base)
        if m:
            return (0, int(m.group(1)), 0, base)
    m = _TIMESTAMP_RE.search(base)
    if m:
        return (1, int(m.group(1)), _file_ctime(f), base)
    return (2, 0, _file_ctime(f), base)


def import_images(root, src_folder, apply=False, insert=None, img_order=None):
    """Doi ten anh da gen thanh IMG-xx trong images/ theo dung thu tu prompt
    (prompts-ALL.txt). Map theo thu tu gen == thu tu prompt. apply=False: chi
    in bang xem truoc.
    Thu tu anh: so thu tu trong ten (neu co) > timestamp 12 chu so trong ten
    > mtime (thoi diem tai ve — chi tin khi tai dung thu tu gen).
    insert = "IMG-12:filename" — anh gen SAU (mtime moi nhat, lech vi tri) duoc rut ra
    khoi chuoi thoi gian va gan vao dung IMG; cac anh con lai map theo thu tu.
    img_order = danh sach IMG id cho san (build_service tinh tu storyboard) —
    doi ten KHONG can audio/prompts-build.py; khong truyen thi doc prompts-build.py."""
    exts = ('.jpg', '.jpeg', '.png', '.webp')
    files = [f for f in glob.glob(os.path.join(src_folder, '*'))
             if os.path.isfile(f) and f.lower().endswith(exts)]
    all_have_order = bool(files) and all(_IMG_ORDER_RE.search(os.path.basename(f)) for f in files)
    files.sort(key=lambda f: _img_sort_key(f, all_have_order))
    # Cảnh báo khi mtime ngược với timestamp trong tên (nghi tải về ngược thứ tự gen).
    ts_files = [f for f in files if _TIMESTAMP_RE.search(os.path.basename(f))]
    if len(ts_files) == len(files) and len(files) > 1:
        by_mtime = [int(_TIMESTAMP_RE.search(os.path.basename(f)).group(1)) for f in files]
        if by_mtime != sorted(by_mtime):
            print("⚠️ Thứ tự tải về (mtime) khác thứ tự timestamp trong tên — có thể tải "
                  "ảnh NGƯỢC thứ tự gen. Kiểm tra bảng map bên dưới trước khi --yes.")
    order = list(img_order) if img_order else canonical_img_order(root)
    if not order:
        sys.exit("Danh sach IMG can co dang rong — chua co storyboard/prompts-build.py")
    if not files:
        sys.exit(f"Khong thay anh nao (.jpg/.jpeg/.png/.webp) trong {src_folder}")

    mapping = []   # [(img, src_path)]
    extra = []
    if insert:
        img_id, fname = insert.split(':', 1)
        if img_id not in order:
            sys.exit(f"--insert: {img_id} khong nam trong danh sach IMG can co")
        matches = [f for f in files if fname in os.path.basename(f)]
        if len(matches) != 1:
            sys.exit(f"--insert: tim thay {len(matches)} file khop '{fname}' — "
                     f"can dung ten file (co the cat bot dau/cuoi)")
        new_file = matches[0]
        files.remove(new_file)
        if len(files) != len(order) - 1:
            sys.exit(f"--insert: sau khi rut '{fname}' con {len(files)} anh, "
                     f"phai bang {len(order) - 1}")
        rest = [i for i in order if i != img_id]
        mapping = list(zip(rest, files)) + [(img_id, new_file)]
    else:
        if len(files) < len(order):
            sys.exit(f"Thieu anh: can {len(order)} IMG, thu muc co {len(files)} file anh "
                     f"(gen theo thu tu prompts-ALL.txt, bo 7 id reuse)")
        mapping = list(zip(order, files[:len(order)]))
        extra = files[len(order):]

    mapping.sort(key=lambda m: int(m[0].split('-')[1]))
    out_dir = os.path.join(root, 'images')
    if apply:
        existing = glob.glob(os.path.join(out_dir, 'IMG-*'))
        if existing:
            sys.exit(f"images/ da co {len(existing)} file — xoa hoac di chuyen truoc "
                     f"khi import (tranh de len anh cu)")
        os.makedirs(out_dir, exist_ok=True)
    print(f"Map {len(mapping)} anh -> IMG-xx{' (voi --insert ' + insert + ')' if insert else ''}:")
    for img, src in mapping:
        print(f"  {img}  <-  {os.path.basename(src)}")
        if apply:
            shutil.move(src, os.path.join(out_dir, f"{img}{os.path.splitext(src)[1].lower()}"))
    if extra:
        print(f"\n⚠️ {len(extra)} anh DU (khong map, de nguyen): "
              f"{[os.path.basename(f) for f in extra]}")
    if apply:
        print(f"\n✅ Da doi ten {len(mapping)} anh vao {out_dir}")
    else:
        print("\n(Xem truoc — them --yes de thuc hien doi ten)")


def srt_to_ass_offset(srt_files, chunk_starts, style=None):
    """Gop nhieu srt (moi file theo chunk, bat dau 0:00) thanh MOT file ASS
    voi offset theo moc audio that. style: dict tu load_sub_style()."""
    def ts2cs(t):  # HH:MM:SS,mmm -> centisecond
        h, m, s = t.split(':')
        s, ms = s.split(',')
        return int(h) * 360000 + int(m) * 6000 + int(s) * 100 + int(ms) // 10

    def cs2ts(cs):
        h, rem = divmod(cs, 360000)
        m, rem = divmod(rem, 6000)
        s, c = divmod(rem, 100)
        return f"{h}:{m:02d}:{s:02d}.{c:02d}"

    events = []
    for f, start in zip(srt_files, chunk_starts):
        with open(f, encoding='utf-8-sig') as fh:
            txt = fh.read()
        for m in re.finditer(
                r'(\d+:\d+:\d+,\d+)\s+-->\s+(\d+:\d+:\d+,\d+)(.*?)(?=\n\n|\Z)', txt, re.S):
            a, b, body = m.group(1), m.group(2), m.group(3)
            # bỏ tag ngắt nghỉ MiniMax (<#1.0#>...) và dòng chỉ có tag pause
            lines = [re.sub(r'<#\s*[\d.]+\s*#>', '', ln).strip()
                     for ln in body.strip().split('\n')]
            lines = [ln for ln in lines if ln]
            if not lines:
                continue
            a_cs = ts2cs(a) + int(start * 100)
            b_cs = ts2cs(b) + int(start * 100)
            text = r'\N'.join(lines)
            events.append((a_cs, b_cs, text))

    events.sort()
    style = style or SUB_DEFAULTS
    align = {"bottom": 2, "top": 8, "middle": 5}[style.get("position", "bottom")]
    bold = -1 if style.get("bold") else 0
    style_line = (
        f"Style: Default,{style['font']},{style['fontsize']},"
        f"{hex_to_ass(style['color'])},&H0000FFFF,{hex_to_ass(style['outline_color'])},"
        f"&H64000000,{bold},0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},"
        f"{align},40,40,{style['margin_v']},128")
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n"
        "WrapStyle: 2\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
        "MarginV, Encoding\n"
        f"{style_line}\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n")
    body = "".join(
        f"Dialogue: 0,{cs2ts(a)},{cs2ts(b)},Default,,0,0,0,,{t}\n"
        for a, b, t in events)
    return header + body, len(events)


def burn_subtitles(video_in, ass_path, video_out):
    """Burn ASS vao video (libass), giu nguyen audio."""
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', video_in,
                    '-vf', f'ass={ass_path}', '-c:a', 'copy', video_out], check=True)


ANIM_MODES = ["none", "zoom", "zoom-out", "pan-h", "pan-v", "auto"]

# ---- Tăng tốc render --------------------------------------------------------
# HW encoder (VideoToolbox trên macOS) nhanh 3-8x libx264; auto-detect 1 lần.
_HW_ENCODER_CACHE = None


def detect_hw_encoder():
    """'h264_videotoolbox' nếu ffmpeg có, ngược lại None (dùng CPU)."""
    global _HW_ENCODER_CACHE
    if _HW_ENCODER_CACHE is None:
        try:
            r = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'],
                               capture_output=True, text=True, timeout=20)
            _HW_ENCODER_CACHE = 'h264_videotoolbox' \
                if 'h264_videotoolbox' in (r.stdout or '') else 'none'
        except Exception:
            _HW_ENCODER_CACHE = 'none'
    return _HW_ENCODER_CACHE if _HW_ENCODER_CACHE != 'none' else None


_HW_BITRATE_BY_W = {1280: '6M', 1920: '12M', 2560: '20M', 3840: '32M'}


def video_codec_args(res, hw='auto', still=True):
    """Args encode video dùng chung mọi pass.

    hw=auto/on → VideoToolbox nếu có (bitrate theo width); else libx264
    preset faster (still=True thêm -tune stillimage cho segment ảnh tĩnh).
    """
    if hw in ('auto', 'on'):
        enc = detect_hw_encoder()
        if enc:
            bitrate = _HW_BITRATE_BY_W.get(res[0] if res else 1920, '12M')
            return ['-c:v', enc, '-b:v', bitrate, '-pix_fmt', 'yuv420p']
    args = ['-c:v', 'libx264', '-preset', 'faster', '-crf', '21']
    if still:
        args += ['-tune', 'stillimage']
    args += ['-pix_fmt', 'yuv420p']
    return args


def audio_codec_args():
    return ['-c:a', 'aac', '-b:a', '192k']


# ---- FX nhieu (grain/glitch/vhs) — ap cho tung segment --------------------
FX_MODES = ["none", "grain", "glitch", "vhs", "auto"]
DEFAULT_FX_GRAIN = 8  # cuong do mac dinh (2-30)


def fx_for(mode, seg_index):
    """auto: da phan segment sach, thi thoang grain/glitch — seed co dinh nen
    render lai ra y he (cung tinh than voi anim_for)."""
    if mode != "auto":
        return mode
    roll = random.Random(777000 + seg_index * 13).random()
    if roll < 0.60:
        return "none"
    if roll < 0.85:
        return "grain"
    return "glitch"


def fx_vf(fx, grain):
    """Filter ffmpeg cho hieu ung nhieu. None = khong ap dung.

    Ap SAU zoompan → grain nam o screen-space, khong bi zoom phong to.
    """
    if fx in ("", "none") or grain <= 0:
        return None
    if fx == "grain":
        return f"noise=alls={grain}:allf=t+u"
    shift = max(2, min(7, round(grain / 3)))
    if fx == "glitch":
        # lech kenh R/B nhu loi tin hieu so + noise
        return f"noise=alls={grain}:allf=t+u,rgbashift=rh=-{shift}:bh={shift}"
    if fx == "vhs":
        # bang tu cu: noise + rgb shift + mo nhe + nhat mau + vignette
        return (f"noise=alls={grain}:allf=t+u,rgbashift=rh=-{shift}:bh={shift},"
                f"gblur=sigma=0.6,eq=saturation=0.82:contrast=1.06,vignette=PI/5")
    return None


def anim_for(mode, seg_index, rng=None):
    """auto: chon nhanh mode cho segment (co dinh theo seed — chay lai van giong)."""
    if mode != "auto":
        return mode
    rng = rng or random.Random(20260803)
    rng.seed(20260803 + seg_index)
    return rng.choice(["zoom", "zoom-out", "pan-h", "pan-v"])


def zoompan_vf(mode, dur, w, h):
    """Filter zoompan theo mode. Tra ve None neu khong can animation.
    Zoom chuan hoa theo do dai segment: dat toi da o frame cuoi (cam giac dong deu).
    Supersample chi 1.3x (du cho zoommax 1.2 + pan) thay vi 2x — giam nang CPU."""
    if mode == "none":
        return None
    frames = max(2, int(dur * FPS))
    zmax = 1.20
    step = f"on/{frames-1}"
    if mode == "zoom":
        z = f"1+({zmax}-1)*{step}"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif mode == "zoom-out":
        z = f"{zmax}-({zmax}-1)*{step}"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif mode == "pan-h":
        z = str(zmax)
        x = f"(iw-iw/zoom)*{step}"
        y = "(ih-ih/zoom)/2"
    elif mode == "pan-v":
        z = str(zmax)
        x = "(iw-iw/zoom)/2"
        y = f"(ih-ih/zoom)*{step}"
    else:
        return None
    sw, sh = int(w * 1.3) // 2 * 2, int(h * 1.3) // 2 * 2
    return (f"scale={sw}:{sh},zoompan=z='{z}':x='{x}':y='{y}':d=1"
            f":s={w}x{h}:fps={FPS},format=yuv420p")


def render_segment(img_path, out, dur, res, mode, fx='none', grain=0, hw='auto'):
    w, h = res
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    zp = zoompan_vf(mode, dur, w, h)
    if zp:
        vf = zp
    extra = fx_vf(fx, grain)
    if extra:
        vf = f"{vf},{extra}"
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-loop', '1', '-framerate', str(FPS), '-i', img_path,
                    '-t', f"{dur:.2f}", '-vf', vf, '-r', str(FPS),
                    *video_codec_args(res, hw, still=True), out], check=True)


def render_segment_clip(clip_path, out, dur, res, fx='none', grain=0, hw='auto'):
    """Clip image-to-video đã có chuyển động sẵn: loop phủ segment dài hơn clip,
    không zoompan (Ken Burns). `-an` bắt buộc — engine mux audio riêng ở cuối."""
    w, h = res
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p")
    extra = fx_vf(fx, grain)
    if extra:
        vf = f"{vf},{extra}"
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-stream_loop', '-1',
                    '-i', clip_path, '-t', f"{dur:.2f}", '-vf', vf,
                    '-an', '-r', str(FPS), *video_codec_args(res, hw, still=False),
                    out], check=True)


def _ass_filter_path(path: str) -> str:
    """Escape đường dẫn cho filter arg của ffmpeg (dấu ' và : là ký tự đặc biệt)."""
    return path.replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")


def concat_with_xfade(seg_files, transition, out, hw='auto', ass_path=None):
    """Nối các segment bằng xfade chéo (re-encode). Tra ve file video da noi.

    ass_path: burn phụ đề NGAY TRONG pass này (tiết kiệm nguyên 1 pass
    encode full-video so với burn riêng sau mux).
    """
    n = len(seg_files)
    t = transition
    inputs = []
    for p in seg_files:
        inputs += ['-i', p]
    # offset từng xfade: O_k = sum(d1..dk) - k*t
    offsets = []
    cum = 0.0
    for k in range(1, n):
        dur = float(subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', seg_files[k - 1]], capture_output=True, text=True).stdout.strip())
        cum += dur
        offsets.append(cum - k * t)
    chain = []
    prev = "0:v"
    for k in range(1, n):
        outl = f"v{k}"
        chain.append(f"[{prev}][{k}:v]xfade=transition=fade:duration={t}:offset={offsets[k-1]:.3f}[{outl}]")
        prev = outl
    if ass_path is not None:
        chain.append(f"[{prev}]ass={ass_path}[vout]")
        prev = "vout"
    fc = ";".join(chain)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *inputs,
                    '-filter_complex', fc, '-map', f"[{prev}]",
                    *video_codec_args(None, hw, still=False), out], check=True)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root = os.path.abspath(sys.argv[1])
    subs = '--subtitles' in sys.argv
    anim = 'zoom' if '--motion' in sys.argv else 'none'
    if '--animation' in sys.argv:
        i = sys.argv.index('--animation')
        if i + 1 >= len(sys.argv):
            sys.exit("--animation can kem mode: none|zoom|zoom-out|pan-h|pan-v|auto")
        anim = sys.argv[i + 1]
        if anim not in ANIM_MODES:
            sys.exit(f"--animation: mode '{anim}' khong hop le — {ANIM_MODES}")
    transition = 0.0
    if '--transition' in sys.argv:
        i = sys.argv.index('--transition')
        if i + 1 >= len(sys.argv):
            sys.exit("--transition can kem so giay (0-1)")
        transition = float(sys.argv[i + 1])
    fx = 'none'
    if '--fx' in sys.argv:
        i = sys.argv.index('--fx')
        if i + 1 >= len(sys.argv):
            sys.exit("--fx can kem mode: none|grain|glitch|vhs|auto")
        fx = sys.argv[i + 1]
        if fx not in FX_MODES:
            sys.exit(f"--fx: mode '{fx}' khong hop le — {FX_MODES}")
    grain = DEFAULT_FX_GRAIN
    if '--grain' in sys.argv:
        i = sys.argv.index('--grain')
        if i + 1 >= len(sys.argv):
            sys.exit(f"--grain can kem cuong do ({DEFAULT_FX_GRAIN}-30)")
        try:
            grain = int(sys.argv[i + 1])
        except ValueError:
            sys.exit("--grain phai la so nguyen")
        if not 2 <= grain <= 30:
            sys.exit("--grain phai nam trong 2-30")
    hw = 'auto'
    if '--hw' in sys.argv:
        i = sys.argv.index('--hw')
        if i + 1 >= len(sys.argv):
            sys.exit("--hw can kem mode: auto|on|off")
        hw = sys.argv[i + 1]
        if hw not in ('auto', 'on', 'off'):
            sys.exit("--hw: mode '%s' khong hop le — auto|on|off" % hw)
    jobs_n = max(1, min(8, (os.cpu_count() or 4) // 2))
    if '--jobs' in sys.argv:
        i = sys.argv.index('--jobs')
        if i + 1 >= len(sys.argv):
            sys.exit("--jobs can kem so luong (1-8)")
        try:
            jobs_n = max(1, min(8, int(sys.argv[i + 1])))
        except ValueError:
            sys.exit("--jobs phai la so nguyen")
    if '--import-images' in sys.argv:
        i = sys.argv.index('--import-images')
        if i + 1 >= len(sys.argv):
            sys.exit("--import-images can kem thu muc anh da gen")
        src_folder = os.path.abspath(sys.argv[i + 1])
        ins = None
        if '--insert' in sys.argv:
            j = sys.argv.index('--insert')
            if j + 1 >= len(sys.argv):
                sys.exit("--insert can kem 'IMG-12:ten_file'")
            ins = sys.argv[j + 1]
        # --img-order: thu tu IMG cho san (build_service tinh tu storyboard) ->
        # doi ten duoc TRUOC khi co audio, khong can prompts-build.py.
        order = None
        if '--img-order' in sys.argv:
            k = sys.argv.index('--img-order')
            if k + 1 >= len(sys.argv):
                sys.exit("--img-order can kem danh sach IMG-xx cach nhau dau phay")
            order = [s.strip() for s in sys.argv[k + 1].split(',') if s.strip()]
            bad = [s for s in order if not re.fullmatch(r'IMG-\d{1,3}', s)]
            if bad:
                sys.exit(f"--img-order co id sai dinh dang: {bad[:3]}")
            if len(set(order)) != len(order):
                sys.exit("--img-order co id trung lap")
        import_images(root, src_folder, apply='--yes' in sys.argv, insert=ins, img_order=order)
        return
    if '--merge-subs' in sys.argv:
        # chỉ gộp srt -> ass (test nhanh, không cần ffmpeg)
        srt_dir = os.path.join(root, 'srt')
        files = sorted(glob.glob(os.path.join(srt_dir, '*.srt')))
        if not files:
            sys.exit(f"Khong thay .srt nao trong {srt_dir}")
        chunks = []
        for f in sorted(glob.glob(os.path.join(root, 'audio', '*.mp3'))):
            r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'csv=p=0', f], capture_output=True, text=True)
            chunks.append(float(r.stdout.strip()))
        starts = [sum(chunks[:k]) for k in range(len(chunks))]
        style = load_sub_style(root, parse_sub_flags(sys.argv))
        ass, n = srt_to_ass_offset(files, starts, style)
        out = os.path.join(root, 'subs-merged.ass')
        with open(out, 'w', encoding='utf-8') as fh:
            fh.write(ass)
        print(f"✅ Gop {len(files)} srt -> {out} ({n} cue, offset theo audio that)")
        print(f"   Style: {style['font']} {style['fontsize']}px · {style['color']} · "
              f"viền {style['outline']}px {style['outline_color']} · bóng {style['shadow']} · "
              f"{style['position']}")
        return
    res = (1280, 720)
    motion = '--motion' in sys.argv
    dry = '--dry-run' in sys.argv
    if '--resolution' in sys.argv:
        i = sys.argv.index('--resolution')
        if i + 1 >= len(sys.argv):
            sys.exit("--resolution can kem gia tri (vd 1920x1080)")
        w, h = sys.argv[i + 1].lower().split('x')
        res = (int(w), int(h))

    segs, _ = parse_segments(root)
    marks = parse_marks(root)
    audio_files, real_total = audio_files_and_total(root)
    real_chunks = []
    for f in audio_files:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'csv=p=0', f], capture_output=True, text=True)
        real_chunks.append(float(r.stdout.strip()))
    if len(real_chunks) != len(marks):
        sys.exit(f"FAIL: {len(real_chunks)} file audio nhung marks.tsv co {len(marks)} section — "
                 f"phai bang nhau (1 audio = 1 chunk = 1 section)")

    # map beat -> chunk theo thoi gian (est time vs audio that tich luy)
    chunk_of = map_beats_to_chunks_by_time(segs, real_chunks)
    quote_info = "map theo thoi gian (khong can IMAGE-PRODUCTION.md)"

    # est duration theo chunk
    est_by_chunk = [0.0] * len(real_chunks)
    for img, b, s, e in segs:
        c = chunk_of.get(b)
        if c is None:
            sys.exit(f"FAIL: beat {b} khong map duoc chunk — kiem tra prompts-build.py / audio")
        est_by_chunk[c] += (e - s)

    # per-chunk scale + gate
    print(f"Segments: {len(segs)} · {quote_info}")
    print(f"\n{'chunk':<6}{'#seg':>5}{'est_sum':>9}{'audio_thật':>12}{'scale':>8}  status")
    print("-" * 52)
    scales = []
    for k in range(len(real_chunks)):
        sc = real_chunks[k] / est_by_chunk[k] if est_by_chunk[k] else 0
        st = "OK"
        if not (SCALE_MIN <= sc <= SCALE_MAX):
            st = f"⚠️ NGOAI {SCALE_MIN}-{SCALE_MAX} — xem lai giờ draft / marks"
        scales.append(sc)
        print(f"  {k+1}   {sum(1 for _, b, _, _ in segs if chunk_of[b] == k):>5}"
              f"{est_by_chunk[k]:>8.1f}s{real_chunks[k]:>11.1f}s{sc:>7.3f}  {st}")

    # scaled durations
    scaled = []
    for img, b, s, e in segs:
        scaled.append(((e - s) * scales[chunk_of[b]], img, b))
    tot = sum(d for d, _, _ in scaled)
    print(f"\nTong sau scale: {tot:.2f}s — audio: {real_total:.2f}s — lech {tot-real_total:+.3f}s")
    if abs(tot - real_total) > 0.15:
        sys.exit("FAIL: lech tong qua 0.15s — kiem tra lai timeline")

    missing = sorted({img for img, b, s, e in segs if not find_image(root, img)})
    if missing:
        sys.exit(f"THIEU {len(missing)} ANH — gen truoc roi dat ten IMG-xx vao {root}/images/:\n  " +
                 ", ".join(missing))

    print(f"\n{'#':>3} {'img':<8} {'chunk':>5} {'that':>7}  {'img file'}")
    print("-" * 42)
    for k, (d, img, b) in enumerate(scaled, 1):
        clip = find_clip(root, img)
        src = os.path.basename(clip) if clip else os.path.basename(find_image(root, img))
        print(f"{k:>3} {img:<8} {chunk_of[b]+1:>5} {d:>6.2f}s  {src}" + (" · CLIP" if clip else ""))
    if dry:
        print("\n(--dry-run: khong rap)")
        return

    tmp = tempfile.mkdtemp(prefix="build-video-")
    try:
        total_seg = len(scaled)
        anim_label = anim if anim != 'auto' else 'auto (xen kẽ zoom/zoom-out/pan)'
        hw_enc = detect_hw_encoder() if hw != 'off' else None
        print(f"Animation: {anim_label}" + (f" · fade {transition:.1f}s" if transition else " · cắt cứng")
              + (f" · FX {fx} (grain {grain})" if fx != 'none' else "")
              + f" · encoder {'h264_videotoolbox' if hw_enc else 'libx264-faster'} · {jobs_n} luồng",
              flush=True)

        # Precompute mọi tham số theo index (deterministic) trước khi chạy parallel —
        # anim_for/fx_for seed theo index nên không phụ thuộc thứ tự hoàn thành.
        tasks = []
        img_anim_idx = 0  # đếm riêng số segment dùng ảnh — clips không tiêu slot auto-animation
        for k, (d, img, b) in enumerate(scaled, 1):
            out = os.path.join(tmp, f"seg_{k:03d}.mp4")
            seg_fx = fx_for(fx, k)
            # bù fade: mỗi segment (trừ cuối) dài thêm `transition` giây để sau xfade
            # tổng video vẫn == tổng audio (không bị -shortest cắt đuôi audio)
            render_dur = d + transition if (transition > 0 and k < total_seg) else d
            clip = find_clip(root, img)
            mode = None
            if not clip:
                mode = anim_for(anim, img_anim_idx)
                img_anim_idx += 1
            tasks.append((k, d, img, out, render_dur, clip, mode, seg_fx))

        def render_one(task):
            k, d, img, out, render_dur, clip, mode, seg_fx = task
            fx_label = f" · FX:{seg_fx}" if seg_fx != 'none' else ""
            clip_label = " · CLIP" if clip else ""
            print(f"[{k}/{total_seg}] dang rap {img} ({d:.1f}s)" + clip_label + fx_label, flush=True)
            if clip:
                clip_dur = float(subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'csv=p=0', clip], capture_output=True, text=True).stdout.strip())
                if clip_dur >= render_dur:
                    # clip đủ dài — dùng clip, không loop
                    render_segment_clip(clip, out, render_dur, res, seg_fx, grain, hw)
                else:
                    # clip ngắn hơn segment: phát hết clip rồi dùng ảnh gốc fill phần còn lại
                    tail_dur = render_dur - clip_dur
                    clip_part = os.path.join(tmp, f"seg_{k:03d}_clip.mp4")
                    still_part = os.path.join(tmp, f"seg_{k:03d}_still.mp4")
                    render_segment_clip(clip, clip_part, clip_dur, res, seg_fx, grain, hw)
                    source_img = find_image(root, img)
                    render_segment(source_img, still_part, tail_dur, res, 'none', seg_fx, grain, hw)
                    listf = os.path.join(tmp, f"seg_{k:03d}_list.txt")
                    with open(listf, 'w', encoding='utf-8') as lf:
                        lf.write(f"file '{clip_part}'\n")
                        lf.write(f"file '{still_part}'\n")
                    # RE-ENCODE: concat copy làm lệch timestamps → xfade nuốt segment.
                    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
                                    '-i', listf, *video_codec_args(res, hw, still=False), out], check=True)
                    print(f"  → [{k}/{total_seg}] clip {clip_dur:.1f}s + ảnh tĩnh {tail_dur:.1f}s", flush=True)
            else:
                render_segment(find_image(root, img), out, render_dur, res, mode, seg_fx, grain, hw)
            print(f"[{k}/{total_seg}] xong {img}", flush=True)

        if jobs_n > 1 and total_seg > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=jobs_n) as pool:
                list(pool.map(render_one, tasks))
        else:
            for task in tasks:
                render_one(task)
        seg_files = [t[3] for t in tasks]

        # Chuẩn bị phụ đề (nếu có) — burn gộp vào pass ghép/mux, bỏ pass riêng.
        ass_path = None
        n_cue = 0
        if subs:
            srt_dir = os.path.join(root, 'srt')
            srt_files = sorted(glob.glob(os.path.join(srt_dir, '*.srt')))
            if not srt_files:
                sys.exit(f"--subtitles: khong thay .srt nao trong {srt_dir}")
            sub_style = load_sub_style(root, parse_sub_flags(sys.argv))
            print(f"Phu de: {len(srt_files)} file srt ({sub_style['font']} "
                  f"{sub_style['fontsize']}px) — burn gộp vào pass ghép...", flush=True)
            ass_path = os.path.join(tmp, "subs.ass")
            ass, n_cue = srt_to_ass_offset(
                srt_files, [0.0] + [sum(real_chunks[:k]) for k in range(1, len(real_chunks))],
                sub_style)
            with open(ass_path, 'w', encoding='utf-8') as fh:
                fh.write(ass)

        print("Rap xong tat ca segment, dang ghep video...", flush=True)
        if transition > 0:
            video_raw = os.path.join(tmp, "video_raw.mp4")
            # ass filter chạy ngay trong pass xfade → tiết kiệm nguyên 1 pass encode
            concat_with_xfade(seg_files, transition, video_raw, hw,
                              _ass_filter_path(ass_path) if ass_path else None)
        else:
            listf = os.path.join(tmp, "video-list.txt")
            with open(listf, 'w', encoding='utf-8') as f:
                for p in seg_files:
                    f.write(f"file '{p}'\n")
            video_raw = os.path.join(tmp, "video_raw.mp4")
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
                            '-i', listf, '-c', 'copy', video_raw], check=True)
        # RE-ENCODE audio thay vì -c copy: các chunk cắt bằng -ss mang header
        # LAME/Xing lệch timestamps → concat copy sinh "non monotonically
        # increasing dts" và audio_concat hỏng ngầm. Re-encode mp3 ~vài chục giây.
        audio_concat = os.path.join(tmp, "audio_concat.mp3")
        alist = os.path.join(tmp, "audio-list.txt")
        with open(alist, 'w', encoding='utf-8') as f:
            for p in audio_files:
                f.write(f"file '{p}'\n")
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
                        '-i', alist, '-c:a', 'libmp3lame', '-q:a', '2', audio_concat], check=True)
        out_video = os.path.join(root, 'video-final.mp4')
        # Kiểm tra video_raw trước khi mux — nếu ngắn (xfade nuốt segment), -shortest
        # sẽ cắt video xuống đúng độ dài lỗi mà không hề báo lỗi.
        vr = float(subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', video_raw], capture_output=True, text=True).stdout.strip())
        if abs(vr - real_total) > 2.0:
            print(f"⚠️  video_raw chỉ dài {vr:.1f}s nhưng audio là {real_total:.1f}s — "
                  f"segment bị mất! Dừng để tránh xuất video cụt.", flush=True)
            sys.exit(f"FAIL: video_raw {vr:.1f}s != audio {real_total:.1f}s — lỗi ghép segment")
        if transition > 0 or not ass_path:
            # phụ đề đã burn trong pass xfade (hoặc không có sub) → mux stream copy
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', video_raw, '-i', audio_concat,
                            '-c:v', 'copy', *audio_codec_args(), '-shortest', out_video],
                           check=True)
        else:
            # transition=0 mà có sub: concat là -c copy nên burn ass ngay trong mux
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', video_raw, '-i', audio_concat,
                            '-vf', f"ass={_ass_filter_path(ass_path)}",
                            *video_codec_args(res, hw, still=False), *audio_codec_args(),
                            '-shortest', out_video], check=True)
        if ass_path is not None:
            print(f"  ({n_cue} cue đã burn vào video)", flush=True)
        dur = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                              '-of', 'csv=p=0', out_video], capture_output=True, text=True)
        d = float(dur.stdout.strip())
        print(f"\n✅ Da tao: {out_video} · {d:.1f}s = {int(d//60)}:{int(d%60):02d}", flush=True)
        if abs(d - real_total) > 2.0:
            print(f"⚠️  Video thành phẩm {d:.1f}s khác audio {real_total:.1f}s — "
                  f"kiểm tra segment bị mất / mux lại!", flush=True)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
