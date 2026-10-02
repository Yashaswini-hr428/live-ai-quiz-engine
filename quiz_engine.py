#!/usr/bin/env python3
"""
Live AI Quiz Engine - pure Python standard library, zero dependencies.

  * HTTP + WebSocket (RFC 6455) server implemented on asyncio
  * AI question generation via the Anthropic API (set ANTHROPIC_API_KEY),
    with an automatic offline question bank fallback
  * Live scoring (speed + streak bonus) and real-time leaderboard
  * Browser frontend (HTML/CSS/JS) served from this same file

Run:   python3 quiz_engine.py            ->  same Wi-Fi only
       python3 quiz_engine.py --public   ->  also gives a public internet link (needs ssh or cloudflared)
Env:   ANTHROPIC_API_KEY, QUIZ_MODEL (default claude-sonnet-5-5), PORT (default 8000)
"""
import asyncio, base64, hashlib, json, os, random, re, secrets, shutil, socket, struct, sys, time
import urllib.parse, urllib.request

PORT = int(os.environ.get("PORT", 8000))
MODEL = os.environ.get("QUIZ_MODEL", "claude-sonnet-5-5")
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# --------------------------------------------------------------------------
# Question generation (AI + offline fallback)
# --------------------------------------------------------------------------
BANK = {
 "python": [
  ("Which keyword defines a function in Python?", ["def", "fn", "function", "define"], "Functions are declared with def."),
  ("What does type([]) return?", ["<class 'list'>", "<class 'tuple'>", "<class 'dict'>", "<class 'set'>"], "[] is an empty list literal."),
  ("Which built-in structure is immutable?", ["tuple", "list", "dict", "set"], "Tuples cannot be modified after creation."),
  ("What does PEP 8 describe?", ["Python code style guide", "Packaging format", "Async API", "Type syntax"], "PEP 8 is the official style guide."),
  ("What does 'self' conventionally refer to in a method?", ["The instance", "The class", "The module", "The parent"], "self is the instance the method is called on."),
 ],
 "science": [
  ("Which gas do plants absorb for photosynthesis?", ["Carbon dioxide", "Oxygen", "Nitrogen", "Hydrogen"], "Plants turn CO2 and water into sugar and oxygen."),
  ("What is the chemical symbol for gold?", ["Au", "Ag", "Go", "Gd"], "Au comes from the Latin 'aurum'."),
  ("Which planet is known as the Red Planet?", ["Mars", "Venus", "Jupiter", "Mercury"], "Iron oxide gives Mars its red colour."),
  ("Roughly how fast does light travel?", ["300,000 km/s", "30,000 km/s", "3,000 km/s", "3 million km/s"], "About 299,792 km/s in vacuum."),
  ("What is the powerhouse of the cell?", ["Mitochondria", "Nucleus", "Ribosome", "Golgi apparatus"], "Mitochondria produce most of the cell's ATP."),
 ],
 "geography": [
  ("What is the capital of Australia?", ["Canberra", "Sydney", "Melbourne", "Perth"], "Canberra was purpose-built as the capital."),
  ("Which river flows through Cairo?", ["Nile", "Congo", "Niger", "Zambezi"], "The Nile runs through Egypt."),
  ("Which is the largest ocean?", ["Pacific", "Atlantic", "Indian", "Arctic"], "The Pacific covers about a third of Earth."),
  ("Mount Everest lies on the border of Nepal and which country?", ["China", "India", "Bhutan", "Pakistan"], "The northern side is in Tibet, China."),
  ("Which city is nicknamed the 'Garden City of India'?", ["Bengaluru", "Mysuru", "Chennai", "Pune"], "Bengaluru is known for its parks and greenery."),
 ],
 "tech computing": [
  ("What does HTTP stand for?", ["HyperText Transfer Protocol", "High Transfer Text Protocol", "Hyper Terminal Tunnel Process", "Host Transfer Task Protocol"], "HTTP is the web's request/response protocol."),
  ("Which protocol enables full-duplex browser-server communication?", ["WebSocket", "FTP", "SMTP", "SSH"], "WebSockets keep one TCP connection open both ways."),
  ("What does CPU stand for?", ["Central Processing Unit", "Computer Personal Unit", "Central Program Utility", "Core Processing Update"], "The CPU executes instructions."),
  ("Which data structure is FIFO?", ["Queue", "Stack", "Tree", "Heap"], "First in, first out."),
  ("What is decimal 5 in binary?", ["101", "110", "011", "111"], "4 + 1 = 5."),
 ],
 "general": [
  ("How many continents are there (common model)?", ["7", "6", "8", "5"], "Africa, Antarctica, Asia, Australia, Europe, N. and S. America."),
  ("Who painted the Mona Lisa?", ["Leonardo da Vinci", "Michelangelo", "Raphael", "Van Gogh"], "Painted in the early 16th century."),
  ("How many minutes are in a day?", ["1440", "1240", "1400", "2400"], "24 x 60 = 1440."),
  ("Which is the largest mammal?", ["Blue whale", "African elephant", "Giraffe", "Hippo"], "Blue whales can exceed 25 metres."),
  ("In which sport is the score 'love' used?", ["Tennis", "Cricket", "Golf", "Rugby"], "Love means zero in tennis."),
 ],
}


def offline_questions(topic, n):
    t = topic.lower()
    pool = [x for k, v in BANK.items() if any(w in t for w in k.split()) or k.split()[0] in t for x in v]
    if len(pool) < n:  # pad with everything else
        rest = [x for v in BANK.values() for x in v if x not in pool]
        random.shuffle(rest)
        pool += rest
    random.shuffle(pool)
    out = []
    for q, opts, ex in pool[:n]:
        o = opts[:]
        random.shuffle(o)
        out.append({"q": q, "o": o, "a": o.index(opts[0]), "e": ex})
    return out


def llm_questions(topic, n):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    prompt = (f"Write {n} multiple-choice quiz questions about: {topic!r}. Vary difficulty. "
              "Return ONLY a JSON array, no prose, no code fences. Each item: "
              '{"q": str, "options": [4 distinct strings], "answer": 0-3 index of the correct option, '
              '"explanation": one short sentence}. Facts must be accurate and unambiguous.')
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({"model": MODEL, "max_tokens": 4000,
                         "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = "".join(b.get("text", "") for b in json.load(r)["content"])
    arr = json.loads(re.search(r"\[.*\]", text, re.S).group())
    out = []
    for x in arr:
        o = [str(s)[:120] for s in x["options"]][:4]
        a = int(x["answer"])
        if len(o) == 4 and 0 <= a < 4 and len(set(o)) == 4:
            out.append({"q": str(x["q"])[:300], "o": o, "a": a, "e": str(x.get("explanation", ""))[:300]})
    return out or None


def parse_custom(text):
    """Blocks separated by a blank line: question, then 2-4 options (correct one starts with *),
    optional '# explanation' line."""
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if len(lines) < 3:
            continue
        opts, ans, ex = [], None, ""
        for l in lines[1:]:
            if l.startswith("#"):
                ex = l[1:].strip()[:300]
                continue
            ok = l.startswith("*")
            l = (l[1:] if ok else l).strip()[:120]
            if l and len(opts) < 4:
                if ok and ans is None:
                    ans = len(opts)
                opts.append(l)
        if len(opts) >= 2 and ans is not None and len(set(opts)) == len(opts):
            out.append({"q": lines[0][:300], "o": opts, "a": ans, "e": ex})
    return out[:50]


CATS = [  # (keywords, Open Trivia DB category id, name)
    (("cinema", "film", "movie", "bollywood", "hollywood", "tollywood", "kollywood", "actor"), 11, "Film"),
    (("music", "song", "singer", "band"), 12, "Music"),
    (("tv", "television", "series", "serial"), 14, "Television"),
    (("video game", "gaming", "game"), 15, "Video Games"),
    (("science", "physics", "chemistry", "biology", "space", "nature"), 17, "Science & Nature"),
    (("computer", "tech", "programming", "python", "coding", "software", "internet"), 18, "Computers"),
    (("math", "algebra", "geometry"), 19, "Mathematics"),
    (("mythology", "myth", "ramayana", "mahabharata", "gods"), 20, "Mythology"),
    (("sport", "cricket", "football", "ipl", "olympic", "tennis"), 21, "Sports"),
    (("geography", "country", "countries", "capital", "world"), 22, "Geography"),
    (("history", "ancient", "war", "freedom", "independence"), 23, "History"),
    (("politic", "government", "leader"), 24, "Politics"),
    (("art", "painting", "painter"), 25, "Art"),
    (("celebrit", "famous"), 26, "Celebrities"),
    (("animal", "wildlife", "pet"), 27, "Animals"),
    (("car", "vehicle", "bike"), 28, "Vehicles"),
    (("comic", "superhero"), 29, "Comics"),
    (("gadget", "phone", "mobile"), 30, "Gadgets"),
    (("anime", "manga"), 31, "Anime & Manga"),
    (("cartoon", "animation"), 32, "Cartoons"),
    (("general", "gk", "trivia", "mixed"), 9, "General Knowledge"),
]


def tdb_questions(topic, n):
    """Free fallback (no key): Open Trivia DB, matched to a broad category. Returns (questions, category name)."""
    t = topic.lower()
    hit = next(((i, nm) for ks, i, nm in CATS if any(k in t for k in ks)), None)
    if not hit:
        return None, None
    url = f"https://opentdb.com/api.php?amount={min(n, 50)}&category={hit[0]}&type=multiple&encode=url3986"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    u, out = urllib.parse.unquote, []
    for x in data.get("results", []):
        right = u(x["correct_answer"])
        opts = [u(o) for o in x["incorrect_answers"]] + [right]
        random.shuffle(opts)
        out.append({"q": u(x["question"]), "o": opts, "a": opts.index(right), "e": ""})
    return out, hit[1]


def bank_matches(topic, n):
    """Built-in questions that really match the topic (may be fewer than n, or none)."""
    t = topic.lower()
    pool = [x for k, v in BANK.items() if any(w in t for w in k.split()) for x in v]
    random.shuffle(pool)
    out = []
    for q, opts, ex in pool[:n]:
        o = opts[:]
        random.shuffle(o)
        out.append({"q": q, "o": o, "a": o.index(opts[0]), "e": ex})
    return out


async def generate(topic, n):
    """Returns (questions, source label, note for the host)."""
    loop, qs, srcs, cat, on_topic = asyncio.get_running_loop(), [], [], None, 0
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    try:
        got = await loop.run_in_executor(None, llm_questions, topic, n)
        if got:
            qs += got
            srcs.append("Claude (AI)")
    except Exception as e:
        print("  [ai] generation failed:", repr(e)[:200])
    if len(qs) < n:  # 1) on-topic questions from the built-in bank
        got = bank_matches(topic, n - len(qs))
        qs, on_topic = qs + got, len(got)
        if got:
            srcs.append("built-in bank")
    if len(qs) < n:  # 2) free general trivia by category
        try:
            got, cat = await loop.run_in_executor(None, tdb_questions, topic, n - len(qs))
            if got:
                qs += got
                srcs.append("Open Trivia DB")
        except Exception as e:
            print("  [trivia] fallback failed:", repr(e)[:120])
    if len(qs) < n:  # 3) pad from the whole bank
        qs += offline_questions(topic, n - len(qs))
        if "built-in bank" not in srcs:
            srcs.append("built-in bank")
    note = ""
    if "Claude (AI)" not in srcs:
        pre = "AI request failed (see terminal). " if has_key else "No API key set. "
        rest = f"general '{cat}' trivia" if cat else "general trivia"
        if on_topic:
            note = pre + f"{on_topic} question(s) are about '{topic}' from the built-in bank; the rest are {rest}."
        else:
            note = pre + f"These are {rest}, not specific to '{topic}'."
    return qs[:n], " + ".join(srcs), note


# --------------------------------------------------------------------------
# Minimal WebSocket implementation (RFC 6455)
# --------------------------------------------------------------------------
class WS:
    def __init__(self, r, w):
        self.r, self.w, self.alive = r, w, True

    async def recv(self):
        buf = b""
        while True:
            b0, b1 = await self.r.readexactly(2)
            fin, op, ln = b0 & 0x80, b0 & 0x0F, b1 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", await self.r.readexactly(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", await self.r.readexactly(8))[0]
            if ln > 1 << 20:
                raise ValueError("frame too large")
            mask = await self.r.readexactly(4) if b1 & 0x80 else None
            data = await self.r.readexactly(ln)
            if mask:
                data = bytes(c ^ mask[i & 3] for i, c in enumerate(data))
            if op == 8:
                return None
            if op == 9:
                await self._frame(0xA, data)
            elif op in (0, 1, 2):
                buf += data
                if fin:
                    return buf.decode()

    async def _frame(self, op, data):
        n = len(data)
        hdr = bytes([0x80 | op]) + (bytes([n]) if n < 126 else b"\x7e" + struct.pack(">H", n)
                                    if n < 65536 else b"\x7f" + struct.pack(">Q", n))
        self.w.write(hdr + data)
        await self.w.drain()

    async def send(self, obj):
        if not self.alive:
            return
        try:
            await self._frame(1, json.dumps(obj).encode())
        except Exception:
            self.alive = False


# --------------------------------------------------------------------------
# Game state
# --------------------------------------------------------------------------
rooms = {}


class Player:
    def __init__(self, name):
        self.name, self.token = name, secrets.token_hex(8)
        self.score = self.streak = self.gain = 0
        self.ans = None      # (choice, elapsed)
        self.ok = None
        self.conn = None


class Conn:
    def __init__(self, ws):
        self.ws, self.role, self.room, self.player = ws, None, None, None


class Room:
    def __init__(self, code, topic, n, secs):
        self.code, self.topic, self.n, self.secs = code, topic, n, secs
        self.token = secrets.token_hex(8)
        self.host, self.players = None, {}
        self.qs, self.i, self.phase, self.t0, self.ai = [], -1, "lobby", 0.0, False
        self.custom, self.n_ai, self.src, self.note = [], 0, "", ""
        self.ev = asyncio.Event()

    def conns(self):
        return ([self.host] if self.host else []) + [p.conn for p in self.players.values() if p.conn]


def ranked(room):
    return sorted(room.players.values(), key=lambda p: -p.score)


def board(room, top=10):
    return [{"name": p.name, "score": p.score, "streak": p.streak, "gain": p.gain, "online": bool(p.conn)}
            for p in ranked(room)[:top]]


def you(room, p):
    if not p:
        return None
    return {"name": p.name, "score": p.score, "gain": p.gain, "streak": p.streak,
            "rank": ranked(room).index(p) + 1, "correct": p.ok if p.ans else None}


def state_msg(room, c):
    p, ph = c.player, room.phase
    if ph == "lobby":
        return {"t": "lobby", "room": room.code, "topic": room.topic, "n": room.n, "secs": room.secs, "custom": len(room.custom),
                "players": [x.name for x in room.players.values()]}
    if ph == "generating":
        return {"t": "generating", "topic": room.topic}
    q = room.qs[room.i]
    if ph == "question":
        rem = max(0, room.secs - (time.time() - room.t0))
        m = {"t": "question", "i": room.i + 1, "n": room.n, "q": q["q"], "o": q["o"], "secs": room.secs,
             "remaining": rem, "answered": sum(1 for x in room.players.values() if x.ans),
             "total": len(room.players), "chosen": p.ans[0] if p and p.ans else None}
        if c.role == "host":
            m["note"] = room.note
        if c.role == "host":
            m["board"] = board(room)
        return m
    if ph == "reveal":
        counts = [sum(1 for x in room.players.values() if x.ans and x.ans[0] == k) for k in range(len(q["o"]))]
        return {"t": "reveal", "i": room.i + 1, "n": room.n, "q": q["q"], "o": q["o"], "a": q["a"],
                "e": q["e"], "counts": counts, "board": board(room), "you": you(room, p),
                "last": room.i + 1 == room.n}
    return {"t": "final", "board": board(room, 20), "you": you(room, p), "src": room.src, "topic": room.topic}


async def bcast(room):
    await asyncio.gather(*(c.ws.send(state_msg(room, c)) for c in room.conns()))


async def run(room):
    try:
        room.phase = "generating"
        await bcast(room)
        room.qs = list(room.custom)
        if room.n_ai:
            ai_qs, label, room.note = await generate(room.topic, room.n_ai)
            room.qs += ai_qs
        room.n = len(room.qs)
        room.src = " + ".join((["host"] if room.custom else []) + ([label] if room.n_ai else []))
        for i in range(room.n):
            room.i, room.t0 = i, time.time()
            for p in room.players.values():
                p.ans, p.gain, p.ok = None, 0, None
            room.phase = "question"
            room.ev.clear()
            await bcast(room)
            try:
                await asyncio.wait_for(room.ev.wait(), room.secs)
            except asyncio.TimeoutError:
                pass
            for p in room.players.values():
                if not p.ans:
                    p.streak = 0
            room.phase = "reveal"
            room.ev.clear()
            await bcast(room)
            try:
                await asyncio.wait_for(room.ev.wait(), 8)
            except asyncio.TimeoutError:
                pass
        room.phase = "final"
        await bcast(room)
        asyncio.get_running_loop().call_later(3600, rooms.pop, room.code, None)
    except Exception as e:
        print("[game] error:", repr(e))


# --------------------------------------------------------------------------
# Message dispatch
# --------------------------------------------------------------------------
async def err(c, msg, fatal=False):
    await c.ws.send({"t": "error", "msg": msg, "fatal": fatal})


async def dispatch(c, m):
    t, room = m.get("t"), c.room
    if t == "create":
        code = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4))
        raw = str(m.get("custom", "")).strip()
        custom, n_ai = parse_custom(raw), max(0, min(15, int(m.get("n", 0))))
        if raw and not custom and not n_ai:
            return await err(c, "Couldn't read your questions - check the format (question, options, * on the correct one)")
        if not custom and not n_ai:
            return await err(c, "Write your own questions or choose AI questions")
        topic = str(m.get("topic", "")).strip()[:80] or ("Custom quiz" if custom else "General knowledge")
        r = Room(code, topic, len(custom) + n_ai, max(5, min(60, int(m.get("secs", 15)))))
        r.custom, r.n_ai = custom, n_ai
        rooms[code] = r
        r.host, c.role, c.room = c, "host", r
        await c.ws.send({"t": "session", "role": "host", "room": code, "token": r.token})
        await c.ws.send(state_msg(r, c))
    elif t == "join":
        r = rooms.get(str(m.get("room", "")).upper().strip())
        name = re.sub(r"\s+", " ", str(m.get("name", ""))).strip()[:16]
        if not r:
            return await err(c, "Room not found")
        if not name:
            return await err(c, "Enter a name")
        if name.lower() in {x.lower() for x in r.players}:
            return await err(c, "Name already taken")
        if len(r.players) >= 200 or r.phase == "final":
            return await err(c, "Room unavailable")
        p = Player(name)
        r.players[name], p.conn, c.player, c.role, c.room = p, c, p, "player", r
        await c.ws.send({"t": "session", "role": "player", "room": r.code, "token": p.token, "name": name})
        await bcast(r) if r.phase == "lobby" else await c.ws.send(state_msg(r, c))
    elif t == "resume":
        r = rooms.get(str(m.get("room", "")))
        if not r:
            return await err(c, "Session expired", True)
        if m.get("role") == "host" and m.get("token") == r.token:
            r.host, c.role, c.room = c, "host", r
        else:
            p = next((x for x in r.players.values() if x.token == m.get("token")), None)
            if not p:
                return await err(c, "Session expired", True)
            p.conn, c.player, c.role, c.room = c, p, "player", r
        await c.ws.send(state_msg(r, c))
    elif not room:
        return
    elif t == "start" and c.role == "host" and room.phase == "lobby":
        if not room.players:
            return await err(c, "Wait for at least one player")
        asyncio.create_task(run(room))
    elif t == "skip" and c.role == "host":
        room.ev.set()
    elif t == "answer" and c.role == "player" and room.phase == "question":
        p, el = c.player, time.time() - room.t0
        ch = int(m.get("choice", -1))
        if p.ans or not 0 <= ch < len(room.qs[room.i]["o"]) or el > room.secs + 1.5:
            return
        p.ans, p.ok = (ch, el), ch == room.qs[room.i]["a"]
        if p.ok:
            p.streak += 1
            p.gain = int(500 + 500 * max(0.0, 1 - el / room.secs)) + min(p.streak - 1, 5) * 50
        else:
            p.streak, p.gain = 0, 0
        p.score += p.gain
        await c.ws.send({"t": "locked", "choice": ch})
        answered = sum(1 for x in room.players.values() if x.ans)
        if room.host:  # live progress + live leaderboard for the host screen
            await room.host.ws.send({"t": "progress", "answered": answered, "total": len(room.players),
                                     "board": board(room)})
        if all(x.ans for x in room.players.values() if x.conn):
            room.ev.set()


# --------------------------------------------------------------------------
# HTTP / WebSocket server
# --------------------------------------------------------------------------
def http(w, code, body, ctype="text/html; charset=utf-8"):
    b = body.encode() if isinstance(body, str) else body
    w.write(f"HTTP/1.1 {code}\r\nContent-Type: {ctype}\r\nContent-Length: {len(b)}\r\n"
            f"Connection: close\r\n\r\n".encode() + b)


async def handle(r, w):
    c = hb = None
    try:
        head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 10)
        lines = head.decode("latin1").split("\r\n")
        path = lines[0].split(" ")[1].split("?")[0]
        hd = {k.strip().lower(): v.strip() for k, v in (l.split(":", 1) for l in lines[1:] if ":" in l)}
        print(f"  [{time.strftime('%H:%M:%S')}] {lines[0][:60]}")
        if path == "/ws" and hd.get("upgrade", "").lower() == "websocket":
            acc = base64.b64encode(hashlib.sha1((hd["sec-websocket-key"] + GUID).encode()).digest()).decode()
            w.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     f"Sec-WebSocket-Accept: {acc}\r\n\r\n").encode())
            await w.drain()
            c = Conn(WS(r, w))

            async def beat():
                while c.ws.alive:
                    await asyncio.sleep(25)
                    try:
                        await c.ws._frame(0x9, b"")
                    except Exception:
                        c.ws.alive = False
            hb = asyncio.create_task(beat())
            while True:
                raw = await c.ws.recv()
                if raw is None:
                    break
                try:
                    await dispatch(c, json.loads(raw))
                except Exception as e:
                    print("[ws] bad message:", repr(e)[:120])
                    await err(c, "Bad request")
        elif path in ("/", "/index.html"):
            http(w, "200 OK", PAGE.replace("__LAN__", PUBLIC_URL or f"http://{lan_ip()}:{PORT}").replace("__PUB__", "1" if PUBLIC_URL else "0"))
            await w.drain()
        else:
            http(w, "404 Not Found", "Not found", "text/plain")
            await w.drain()
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, ValueError, KeyError, IndexError):
        pass
    finally:
        if hb:
            hb.cancel()
        if c:
            c.ws.alive = False
            if c.player and c.player.conn is c:
                c.player.conn = None
            if c.room and c.role == "host" and c.room.host is c:
                c.room.host = None
        try:
            w.close()
        except Exception:
            pass


PUBLIC_URL, TUNNEL = None, None
URL_RE = re.compile(r"https://(?!api\.)[a-z0-9-]+\.(?:trycloudflare\.com|lhr\.life)")


async def start_tunnel():
    """Expose this server on the internet through an outbound tunnel (cloudflared, else ssh/localhost.run)."""
    global PUBLIC_URL, TUNNEL
    if shutil.which("cloudflared"):
        cmd, how = ["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"], "cloudflared"
    elif shutil.which("ssh"):
        cmd, how = ["ssh", "-T", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=30",
                    "-o", "ExitOnForwardFailure=yes", "-R", f"80:127.0.0.1:{PORT}", "nokey@localhost.run"], "ssh (localhost.run)"
    else:
        print("  --public needs 'ssh' or 'cloudflared' installed. Install one, or see the README notes.\n")
        return
    print(f"  Opening public link via {how} ... (up to 40s)")
    TUNNEL = proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    found = asyncio.get_running_loop().create_future()

    async def pump():
        async for line in proc.stdout:
            text = line.decode(errors="ignore")
            if re.search(r"error|fail|refused|denied|closed|timed out", text, re.I):
                print("  [tunnel]", text.strip())
            m = URL_RE.search(text)
            if m and not found.done():
                found.set_result(m.group())
        if found.done() and found.result():
            print("\n  Public tunnel closed - restart the program to get a new link.\n")
        elif not found.done():
            found.set_result(None)

    asyncio.create_task(pump())
    try:
        PUBLIC_URL = await asyncio.wait_for(found, 40)
    except asyncio.TimeoutError:
        PUBLIC_URL = None
    if not PUBLIC_URL:
        print("  Could not open a public link (no internet, or ssh/cloudflared is blocked on this network).\n"
              "  The quiz still works on your local Wi-Fi.\n")
        proc.terminate()


def setup_key():
    """Get the API key from env, api_key.txt, or an interactive prompt."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    f, k = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_key.txt"), ""
    try:
        if os.path.exists(f):
            k = open(f).read().strip()
        elif sys.stdin and sys.stdin.isatty():
            print("\n  No API key found. Paste your Anthropic API key to get AI questions on ANY topic,\n"
                  "  or just press Enter to skip (a free trivia fallback is used instead).")
            k = input("  API key: ").strip()
            if k and input("  Save it to api_key.txt next to this file for next time? (y/N): ").strip().lower() == "y":
                open(f, "w").write(k)
    except Exception:
        return
    if k:
        os.environ["ANTHROPIC_API_KEY"] = k


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "localhost"


async def main():
    try:
        srv = await asyncio.start_server(handle, "0.0.0.0", PORT)
    except OSError:
        print(f"\n  Port {PORT} is already in use. Close the other copy of this program, "
              f"or pick another port, e.g.  PORT=9000 python3 quiz_engine.py\n")
        raise SystemExit(1)
    mode = f"AI questions via {MODEL}" if os.environ.get("ANTHROPIC_API_KEY") else \
        "offline question bank (set ANTHROPIC_API_KEY for AI-generated questions)"
    print(f"\n  Live AI Quiz Engine\n  Host:    http://localhost:{PORT}\n  Players: http://{lan_ip()}:{PORT}\n  Mode:    {mode}\n")
    try:
        import webbrowser
        webbrowser.open(f"http://localhost:{PORT}")   # opens the host page automatically
    except Exception:
        pass
    if "--public" in sys.argv or os.environ.get("PUBLIC"):
        await start_tunnel()
        if PUBLIC_URL:
            print(f"\n  PUBLIC LINK (works on any internet): {PUBLIC_URL}\n")
    else:
        print("  Friends on other networks? Restart with:  python3 quiz_engine.py --public\n")
    print("  Server is running. Keep this window open. Press Ctrl+C to stop.\n")
    async with srv:
        await srv.serve_forever()


# --------------------------------------------------------------------------
# Frontend (served at /)
# --------------------------------------------------------------------------
PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Live AI Quiz</title>
<style>
:root{--bg:#0f1220;--card:#1a1f36;--ink:#eef0ff;--mut:#9aa3c7;--acc:#7c5cff;--ok:#2ecc71;--bad:#ff5c6c;
--c0:#e74c5e;--c1:#3b82f6;--c2:#f5a623;--c3:#22b07d}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1200px 600px at 20% -10%,#262b55,var(--bg));color:var(--ink);
font:16px/1.4 system-ui,sans-serif;min-height:100vh}
main{max-width:860px;margin:0 auto;padding:20px}h1{margin:.2em 0;font-size:1.6rem}
.logo{color:var(--acc)}.card{background:var(--card);border-radius:16px;padding:20px;margin:14px 0;box-shadow:0 8px 30px #0005}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
input,select,textarea{width:100%;padding:12px;margin:6px 0 12px;border-radius:10px;border:1px solid #323a66;background:#0f1328;color:var(--ink);font-size:1rem}
button{cursor:pointer;border:0;border-radius:12px;padding:12px 18px;font-size:1rem;font-weight:700;color:#fff;background:var(--acc)}
button:disabled{opacity:.5;cursor:default}.sec{background:#323a66}
.code{font-size:3.4rem;font-weight:800;letter-spacing:.2em;text-align:center;color:var(--acc)}
textarea{font-family:inherit;resize:vertical}.mut{color:var(--mut)}.center{text-align:center}.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{background:#262d52;padding:6px 12px;border-radius:99px}
.q{font-size:1.5rem;font-weight:700;margin:10px 0 18px}.opts{display:grid;gap:12px;grid-template-columns:1fr 1fr}
@media(max-width:560px){.opts{grid-template-columns:1fr}}
.opt{padding:18px;text-align:left;font-size:1.05rem;position:relative}
.opt:nth-child(1){background:var(--c0)}.opt:nth-child(2){background:var(--c1)}
.opt:nth-child(3){background:var(--c2)}.opt:nth-child(4){background:var(--c3)}
.opt.dim{opacity:.35}.opt.right{outline:4px solid #fff}.opt .n{float:right;font-weight:800}
.bar{height:10px;background:#262d52;border-radius:9px;overflow:hidden}.bar>i{display:block;height:100%;background:var(--acc);width:100%}
.top{display:flex;justify-content:space-between;align-items:center}.timer{font-size:1.6rem;font-weight:800}
.row{display:grid;grid-template-columns:34px 1fr auto;gap:10px;align-items:center;margin:8px 0}
.rk{font-weight:800;color:var(--mut)}.nm{position:relative;background:#262d52;border-radius:9px;padding:8px 12px;overflow:hidden}
.nm i{position:absolute;inset:0 auto 0 0;background:linear-gradient(90deg,#5b43d6,#7c5cff);opacity:.55;transition:width .6s}
.nm span{position:relative}.pts{font-weight:800;min-width:86px;text-align:right}.gain{color:var(--ok);font-size:.85rem;margin-left:6px}
.off{opacity:.45}.me .nm{outline:2px solid var(--ok)}
.res{font-size:1.4rem;font-weight:800}.good{color:var(--ok)}.bad{color:var(--bad)}
#conn{position:fixed;top:0;left:0;right:0;background:var(--bad);text-align:center;padding:6px;z-index:9}
.pod{display:flex;gap:10px;align-items:flex-end;justify-content:center;margin:20px 0}
.pod div{background:#262d52;border-radius:12px 12px 0 0;padding:12px;text-align:center;min-width:90px}
</style></head><body><div id="conn" hidden>Reconnecting&hellip;</div>
<main><h1>&#9889; Live <span class="logo">AI Quiz</span></h1><div id="app"></div></main>
<script>
const $=s=>document.querySelector(s),
esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const LAN='__LAN__',PUB='__PUB__'=='1',base=()=>/^(localhost|127\.|\[::1\])/.test(location.hostname)?LAN:location.origin;
let ws,sess=JSON.parse(sessionStorage.getItem('qs')||'null'),cur=null,end=0,retry=0,errMsg='';
const send=o=>ws&&ws.readyState==1&&ws.send(JSON.stringify(o));
function connect(){
  ws=new WebSocket((location.protocol=='https:'?'wss://':'ws://')+location.host+'/ws');
  ws.onopen=()=>{retry=0;$('#conn').hidden=true;sess?send({t:'resume',...sess}):draw()};
  ws.onmessage=e=>on(JSON.parse(e.data));
  ws.onclose=()=>{$('#conn').hidden=false;setTimeout(connect,Math.min(800*++retry,5000))};
}
function on(m){
  if(m.t=='session'){sess={role:m.role,room:m.room,token:m.token,name:m.name};sessionStorage.setItem('qs',JSON.stringify(sess));return}
  if(m.t=='error'){errMsg=m.msg;if(m.fatal){sess=null;cur=null;sessionStorage.removeItem('qs')}draw();return}
  if(m.t=='locked'){cur.chosen=m.choice;draw();return}
  if(m.t=='progress'&&cur&&cur.t=='question'){Object.assign(cur,m);const a=$('#ans');if(a)a.textContent=m.answered+' / '+m.total+' answered';const b=$('#lb');if(b)b.innerHTML=lb(m.board);return}
  if(m.t=='question')end=Date.now()+m.remaining*1000;
  errMsg='';cur=m;draw();
}
const isHost=()=>sess&&sess.role=='host';
function lb(rows,me){
  const max=Math.max(1,...rows.map(r=>r.score));
  return rows.map((r,i)=>`<div class="row ${r.online?'':'off'} ${me==r.name?'me':''}"><div class="rk">${i+1}</div>
  <div class="nm"><i style="width:${r.score/max*100}%"></i><span>${esc(r.name)}${r.streak>1?' &#128293;'+r.streak:''}</span></div>
  <div class="pts">${r.score}${r.gain?`<span class="gain">+${r.gain}</span>`:''}</div></div>`).join('')||'<p class="mut">No players yet</p>';
}
function draw(){
  const A=$('#app'),m=cur,e=errMsg?`<p class="bad">${esc(errMsg)}</p>`:'';
  if(!m){
    const rc=new URLSearchParams(location.search).get('room')||'';
    A.innerHTML=`${e}<div class="grid"><div class="card"><h2>Join a game</h2>
    <label>Room code</label><input id="rc" maxlength="4" value="${esc(rc)}" style="text-transform:uppercase">
    <label>Your name</label><input id="nm" maxlength="16"><button onclick="join()">Join</button></div>
    <div class="card"><h2>Host a game</h2><label>Topic (AI writes questions from this)</label>
    <input id="tp" placeholder="e.g. Black holes, Indian cinema, Python" maxlength="80">
    <label>AI questions to add</label><select id="nq"><option>0<option>5<option selected>8<option>10<option>15</select>
    <label>Your own questions (optional)</label><textarea id="cq" rows="7" placeholder="Capital of France?&#10;*Paris&#10;Rome&#10;Madrid&#10;# Paris is on the Seine.&#10;&#10;Is the Earth round?&#10;*Yes&#10;No"></textarea>
    <p class="mut" style="margin:-6px 0 12px;font-size:.85rem">Blank line between questions. Put * before the correct option. 2-4 options. Optional # explanation line.</p>
    <label>Seconds per question</label><select id="sc"><option>10<option selected>15<option>20<option>30</select>
    <button onclick="host()">Create room</button></div></div>`;return}
  if(m.t=='generating'){A.innerHTML=`<div class="card center"><h2>&#129302; Generating questions&hellip;</h2><p class="mut">Topic: ${esc(m.topic)}</p></div>`;return}
  if(m.t=='lobby'){
    A.innerHTML=`${e}<div class="card"><p class="center mut">Players open this link</p><p class="center"><b>${esc(base())}</b></p><p class="center mut">and enter code</p>${isHost()&&!PUB&&/^(localhost|127\.|192\.168\.|10\.|172\.)/.test(location.hostname)?'<p class="center bad" style="font-size:.85rem">This link only works on the same Wi-Fi. For players on other networks, restart with: python3 quiz_engine.py --public</p>':''}<div class="code">${m.room}</div>
    <p class="center mut">Topic: <b>${esc(m.topic)}</b> &middot; ${m.n} questions${m.custom?' ('+m.custom+' of your own)':''} &middot; ${m.secs}s each</p></div>
    <div class="card"><h3>Players (${m.players.length})</h3><div class="chips">${m.players.map(p=>`<span class="chip">${esc(p)}</span>`).join('')||'<span class="mut">Waiting for players&hellip;</span>'}</div></div>
    ${isHost()?`<p class="center"><button class="sec" onclick="copyLink('${m.room}')">Copy invite link</button> <button class="sec" onclick="wa('${m.room}')">Share on WhatsApp</button></p>`:''}
    ${isHost()?'<button onclick="send({t:\'start\'})">Start quiz</button>':'<p class="center mut">Waiting for the host to start&hellip;</p>'}`;return}
  if(m.t=='question'){
    const ch=m.chosen;
    A.innerHTML=`${e}<div class="card"><div class="top"><span class="mut">Question ${m.i}/${m.n}</span><span class="timer" id="sec"></span></div>
    <div class="bar"><i id="bar"></i></div>${isHost()&&m.note?`<p class="bad" style="font-size:.85rem;margin:8px 0 0">&#9888; ${esc(m.note)}</p>`:''}<div class="q">${esc(m.q)}</div>
    <div class="opts">${m.o.map((o,k)=>`<button class="opt ${ch!=null&&ch!=k?'dim':''}" ${isHost()||ch!=null?'disabled':''} onclick="send({t:'answer',choice:${k}})">${'ABCD'[k]}. ${esc(o)}</button>`).join('')}</div>
    <p class="center mut">${isHost()?`<span id="ans">${m.answered} / ${m.total} answered</span> &middot; <a href="#" onclick="send({t:'skip'});return false" style="color:var(--acc)">end question</a>`:ch!=null?'Locked in! Waiting for others&hellip;':'Pick fast &mdash; faster answers earn more points'}</p></div>
    ${isHost()?`<div class="card"><h3>Live leaderboard</h3><div id="lb">${lb(m.board||[])}</div></div>`:''}`;return}
  if(m.t=='reveal'){
    const y=m.you,mx=Math.max(1,...m.counts);
    A.innerHTML=`<div class="card"><div class="top"><span class="mut">Question ${m.i}/${m.n}</span></div><div class="q">${esc(m.q)}</div>
    <div class="opts">${m.o.map((o,k)=>`<div class="opt ${k==m.a?'right':'dim'}" style="opacity:${k==m.a?1:.45}">${'ABCD'[k]}. ${esc(o)}<span class="n">${m.counts[k]}</span></div>`).join('')}</div>
    ${m.e?`<p class="mut">&#128161; ${esc(m.e)}</p>`:''}
    ${y?`<p class="res ${y.correct?'good':'bad'}">${y.correct==null?'No answer':y.correct?'Correct! +'+y.gain:'Wrong'} &middot; ${y.score} pts &middot; rank #${y.rank}</p>`:''}
    ${isHost()?`<button class="sec" onclick="send({t:'skip'})">${m.last?'Show final results':'Next question'}</button>`:''}</div>
    <div class="card"><h3>Leaderboard</h3>${lb(m.board,sess&&sess.name)}</div>`;return}
  if(m.t=='final'){
    const t=m.board.slice(0,3),y=m.you;
    A.innerHTML=`<div class="card center"><h2>&#127942; Final results</h2><p class="mut">${esc(m.topic)} &middot; questions by ${esc(m.src)}</p>
    <div class="pod">${t.map((p,i)=>`<div style="height:${130-i*25}px"><div style="background:none;padding:0">${['&#129351;','&#129352;','&#129353;'][i]}</div><b>${esc(p.name)}</b><br>${p.score}</div>`).join('')}</div>
    ${y?`<p class="res">You finished #${y.rank} with ${y.score} pts</p>`:''}</div>
    <div class="card"><h3>Leaderboard</h3>${lb(m.board,sess&&sess.name)}</div>
    <button onclick="sessionStorage.clear();location.href='/'">Play again</button>`;return}
}
const inv=r=>base()+'/?room='+r;
function copyLink(r){const u=inv(r),f=()=>prompt('Copy this link:',u);navigator.clipboard?navigator.clipboard.writeText(u).then(()=>alert('Link copied!'),f):f()}
function wa(r){window.open('https://wa.me/?text='+encodeURIComponent('Join my quiz! '+inv(r)+' (code: '+r+')'))}
function join(){send({t:'join',room:$('#rc').value,name:$('#nm').value})}
function host(){const c=$('#cq').value.trim(),t=$('#tp').value.trim();send({t:'create',topic:t,custom:c,n:c&&!t?0:+$('#nq').value,secs:+$('#sc').value})}
setInterval(()=>{if(!cur||cur.t!='question')return;const l=Math.max(0,end-Date.now()),b=$('#bar'),s=$('#sec');
  if(b)b.style.width=l/(cur.secs*1000)*100+'%';if(s)s.textContent=Math.ceil(l/1000)},100);
connect();
</script></body></html>"""

if __name__ == "__main__":
    import atexit
    setup_key()
    atexit.register(lambda: TUNNEL and TUNNEL.returncode is None and TUNNEL.terminate())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except SystemExit:
        input("Press Enter to close...")
    except Exception as e:
        print("\nSomething went wrong:", repr(e))
        input("Press Enter to close...")
