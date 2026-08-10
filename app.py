#!/usr/bin/env python3
"""
Pantry — a household inventory tracker.
Self-hosted Flask app. Runs on a Raspberry Pi, used by everyone on the LAN.
"""
import os
import sqlite3
import time
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, g, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "pantry.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "data", "photos")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")

# ---------------------------------------------------------------- DB helpers

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL DEFAULT 'grocery',   -- 'grocery' | 'supply'
    subtype       TEXT,                              -- e.g. Detergent, Produce
    upc           TEXT,
    quantity      INTEGER NOT NULL DEFAULT 1,
    unit          TEXT DEFAULT 'unit',
    photo         TEXT,                              -- filename in data/photos
    bought_at     TEXT NOT NULL,                     -- ISO date
    expires_at    TEXT,                              -- ISO date, best-by / est.
    added_by      TEXT DEFAULT 'house',
    notes         TEXT,
    consumed      INTEGER NOT NULL DEFAULT 0,        -- 0 in stock, 1 used up
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_cat ON items(category);
CREATE INDEX IF NOT EXISTS idx_items_consumed ON items(consumed);

CREATE TABLE IF NOT EXISTS grocery_list (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    added_by    TEXT DEFAULT 'someone',   -- who put it on the list
    checked     INTEGER NOT NULL DEFAULT 0,  -- 0 to-buy, 1 grabbed this trip
    checked_by  TEXT,                     -- who checked it off
    created_at  TEXT NOT NULL,
    checked_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_glist_checked ON grocery_list(checked);

CREATE TABLE IF NOT EXISTS upc_catalog (
    upc         TEXT PRIMARY KEY,         -- the barcode
    name        TEXT NOT NULL,
    category    TEXT DEFAULT 'grocery',   -- 'grocery' | 'supply'
    subtype     TEXT,                     -- the category/type label
    added_by    TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'grocery',  -- which list: 'grocery' | 'supply'
    created_at  TEXT NOT NULL,
    UNIQUE(name, kind)
);
"""

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL;")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    # Migration: add expires_at to databases created before this column existed.
    cols = [r[1] for r in con.execute("PRAGMA table_info(items)").fetchall()]
    if "expires_at" not in cols:
        con.execute("ALTER TABLE items ADD COLUMN expires_at TEXT")
    # Seed default categories once (only if the table is empty, so we never
    # fight the household's own edits/deletions on later restarts).
    have = con.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    if have == 0:
        defaults = {
            "grocery": ["Produce", "Dairy", "Meat", "Seafood", "Bakery",
                        "Frozen", "Pantry", "Snacks", "Beverages", "Condiments"],
            "supply": ["Detergent", "Paper goods", "Cleaning", "Toiletries",
                       "Kitchen", "Laundry", "Pet", "Other"],
        }
        now = datetime.now(timezone.utc).isoformat()
        for kind, names in defaults.items():
            for n in names:
                con.execute(
                    "INSERT OR IGNORE INTO categories (name, kind, created_at) VALUES (?,?,?)",
                    (n, kind, now),
                )
    con.commit()
    con.close()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def today():
    return datetime.now().strftime("%Y-%m-%d")

# ---------------------------------------------------------------- Freshness

# Estimated shelf life (days from purchase) by keyword. First match wins, so
# more specific terms are listed before general ones. Used only to pre-fill a
# best-by date; anyone can override it when adding the item.
SHELF_LIFE = [
    # very perishable
    (["fish", "salmon", "tuna", "shrimp", "seafood"], 2),
    (["ground beef", "ground turkey", "mince"], 2),
    (["berr", "strawberr", "raspberr", "blueberr"], 4),
    (["spinach", "lettuce", "salad", "arugula", "kale", "herb", "cilantro", "basil"], 5),
    (["chicken", "pork", "steak", "beef", "meat"], 4),
    (["milk", "cream", "yogurt", "yoghurt"], 7),
    (["bread", "bagel", "tortilla", "bun"], 6),
    (["banana"], 5),
    (["avocado", "tomato", "pepper", "cucumber", "mushroom", "broccoli",
      "zucchini", "asparagus", "grape"], 7),
    (["cheese", "butter", "egg", "tofu", "hummus"], 21),
    (["apple", "orange", "lemon", "lime", "citrus", "carrot", "celery",
      "cabbage", "beet"], 21),
    (["potato", "onion", "garlic", "squash", "pumpkin"], 40),
    # pantry / long-life
    (["frozen", "freezer"], 180),
    (["can", "canned", "jar", "pasta", "rice", "flour", "sugar", "oat",
      "cereal", "bean", "lentil", "sauce", "oil", "vinegar", "honey",
      "spice", "coffee", "tea"], 365),
]

def estimate_expiry(name, subtype, bought_at):
    hay = f"{name} {subtype or ''}".lower()
    days = None
    for keys, d in SHELF_LIFE:
        if any(k in hay for k in keys):
            days = d
            break
    if days is None:
        days = 14  # unknown grocery: a fortnight is a safe nudge, not a guess
    try:
        base = datetime.strptime(bought_at, "%Y-%m-%d")
    except (ValueError, TypeError):
        base = datetime.now()
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")

def freshness(expires_at, category):
    """Return (status, days_left). Status: fresh | soon | urgent | expired | none."""
    if category == "supply" or not expires_at:
        return ("none", None)
    try:
        exp = datetime.strptime(expires_at, "%Y-%m-%d").date()
    except ValueError:
        return ("none", None)
    days = (exp - datetime.now().date()).days
    if days < 0:
        return ("expired", days)
    if days <= 1:
        return ("urgent", days)
    if days <= 4:
        return ("soon", days)
    return ("fresh", days)

def row_to_dict(r):
    d = dict(r)
    if d.get("photo"):
        d["photo_url"] = f"/photos/{d['photo']}"
    else:
        d["photo_url"] = None
    status, days = freshness(d.get("expires_at"), d.get("category"))
    d["freshness"] = status
    d["days_left"] = days
    return d

# ---------------------------------------------------------------- UPC lookup

def lookup_upc(upc):
    """Query Open Food Facts (free, no key). Returns dict or None.

    Never raises: any network, decoding, or parsing problem returns None so the
    caller can fall back to a blank item with just the scanned UPC.
    """
    url = f"https://world.openfoodfacts.org/api/v2/product/{upc}.json"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "PantryTracker/1.0",
            # Ask for an uncompressed response so we don't have to gunzip.
            "Accept-Encoding": "identity",
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
            # Belt-and-braces: if the server compressed anyway (gzip magic
            # bytes 0x1f 0x8b), decompress before decoding.
            if raw[:2] == b"\x1f\x8b":
                import gzip
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8", errors="replace"))
        if data.get("status") == 1:
            p = data["product"]
            name = p.get("product_name") or p.get("generic_name") or ""
            cats = p.get("categories_tags", [])
            subtype = ""
            if cats:
                subtype = cats[-1].split(":")[-1].replace("-", " ").title()
            return {
                "name": name.strip(),
                "subtype": subtype,
                "category": "grocery",
                "brand": p.get("brands", ""),
            }
    except Exception:
        # Any failure at all — connectivity, TLS, compression, malformed JSON —
        # is non-fatal: the scan still works, the user just types the name.
        pass
    return None

# ---------------------------------------------------------------- Recipe logic

# Lightweight rule engine: maps pantry keywords to suggestable meals.
RECIPES = [
    ("Pasta with tomato sauce", ["pasta", "tomato", "garlic", "onion"]),
    ("Grilled cheese", ["bread", "cheese", "butter"]),
    ("Scrambled eggs", ["egg", "butter", "milk"]),
    ("Rice & beans", ["rice", "bean", "onion"]),
    ("Chicken stir fry", ["chicken", "rice", "pepper", "onion", "soy"]),
    ("Pancakes", ["flour", "egg", "milk", "sugar", "butter"]),
    ("Veggie soup", ["carrot", "onion", "potato", "celery", "stock"]),
    ("Tacos", ["tortilla", "beef", "cheese", "onion", "tomato"]),
    ("Oatmeal", ["oat", "milk", "banana", "honey"]),
    ("Caesar salad", ["lettuce", "cheese", "bread", "chicken"]),
    ("Omelette", ["egg", "cheese", "pepper", "onion"]),
    ("Spaghetti bolognese", ["pasta", "beef", "tomato", "onion", "garlic"]),
]

def suggest_recipes(names):
    hay = " ".join(names).lower()
    out = []
    for title, ings in RECIPES:
        have = [i for i in ings if i in hay]
        if len(have) >= 2:
            out.append({
                "title": title,
                "have": have,
                "missing": [i for i in ings if i not in hay],
                "match": round(len(have) / len(ings), 2),
            })
    out.sort(key=lambda x: (-x["match"], len(x["missing"])))
    return out[:6]

# --- TheMealDB (free online recipe database) --------------------------------

# Descriptor words that appear in grocery names but aren't the ingredient itself.
_STOP = {"organic", "fresh", "free", "range", "large", "small", "medium",
         "whole", "reduced", "fat", "low", "lean", "boneless", "skinless",
         "raw", "ripe", "the", "a", "of", "and", "with", "plain", "natural",
         "unsalted", "salted", "brand", "value", "pack", "bag", "box",
         "can", "canned", "jar", "bottle", "frozen", "sliced", "diced",
         "chopped", "baby", "mini", "extra", "virgin", "light", "dark"}

# Cached TheMealDB ingredient vocabulary: lowercase ingredient name -> canonical.
# Populated on first use from list.php?i=list, so matching uses only *real*
# ingredients (e.g. "butternut squash" as one item, never split into "butter").
_INGREDIENT_VOCAB = {"data": None, "fetched_at": 0}

def _load_ingredient_vocab():
    """Fetch and cache TheMealDB's full ingredient list. Returns a dict of
    lowercase name -> canonical name, or {} if unavailable."""
    import time as _t
    cache = _INGREDIENT_VOCAB
    # Refresh at most once a day; the list rarely changes.
    if cache["data"] is not None and (_t.time() - cache["fetched_at"] < 86400):
        return cache["data"]
    url = "https://www.themealdb.com/api/json/v1/1/list.php?i=list"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "PantryTracker/1.0", "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                import gzip; raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8", errors="replace"))
        vocab = {}
        for row in (data.get("meals") or []):
            nm = (row.get("strIngredient") or "").strip()
            if nm:
                vocab[nm.lower()] = nm
        if vocab:
            cache["data"] = vocab
            cache["fetched_at"] = _t.time()
            return vocab
    except Exception:
        pass
    return cache["data"] or {}

def _singularize(w):
    if w.endswith("ies") and len(w) > 4: return w[:-3] + "y"
    if w.endswith("oes") and len(w) > 4: return w[:-2]
    if w.endswith("es") and len(w) > 4:  return w[:-1]
    if w.endswith("s") and len(w) > 3:   return w[:-1]
    return w

def _match_known_ingredients(name, vocab):
    """Find which real TheMealDB ingredients appear in a grocery name. Matches
    whole known ingredients longest-first, so 'Butternut Squash Ravioli' yields
    'Butternut Squash' (not 'butter' + 'squash'), and consumed words can't be
    reused by shorter fragments."""
    text = " " + " ".join(
        _singularize(w.strip(",.()").lower()) for w in name.split()
    ) + " "
    # Candidate known ingredients, longest (most words) first.
    found = []
    for lc in sorted(vocab.keys(), key=lambda s: -len(s.split())):
        probe = " " + lc + " "
        if probe in text:
            found.append(vocab[lc])
            text = text.replace(probe, "  ")   # consume so fragments can't re-match
    return found

def _fallback_keywords(name):
    """When the vocab is unavailable, fall back to conservative single words —
    but never split a name so aggressively that fragments mislead. Uses only the
    single most significant word to avoid the butter/squash problem."""
    words = [_singularize(w.strip(",.()").lower()) for w in name.split()]
    words = [w for w in words if w and w not in _STOP and len(w) > 2]
    return words[-1:] if words else []   # last word is usually the head noun

def _mealdb_filter(ingredient):
    """Return list of {idMeal,strMeal,strMealThumb} for one ingredient, or []."""
    url = f"https://www.themealdb.com/api/json/v1/1/filter.php?i={urllib.parse.quote(ingredient)}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "PantryTracker/1.0", "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                import gzip; raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8", errors="replace"))
        return data.get("meals") or []
    except Exception:
        return []

def suggest_recipes_online(names):
    """Query TheMealDB by the real ingredients found in the household's groceries,
    then rank meals by how many distinct ingredients they use. Falls back to the
    offline list on any failure so the Cook tab is never empty."""
    vocab = _load_ingredient_vocab()
    # Map each searchable ingredient -> the grocery it came from.
    ing_map = {}
    for n in names:
        matches = _match_known_ingredients(n, vocab) if vocab else _fallback_keywords(n)
        for ing in matches:
            ing_map.setdefault(ing.lower(), n)
    if not ing_map:
        return {"recipes": suggest_recipes(names), "source": "offline"}

    # Query each ingredient (single-ingredient filter works on the free key).
    # meal_id -> {meal, matched_ingredients set}
    hits = {}
    any_success = False
    for kw in list(ing_map.keys())[:12]:   # cap total API calls
        meals = _mealdb_filter(kw)
        if meals:
            any_success = True
        for m in meals:
            mid = m.get("idMeal")
            if not mid:
                continue
            e = hits.setdefault(mid, {"id": mid, "title": m.get("strMeal", ""),
                                      "thumb": m.get("strMealThumb", ""),
                                      "uses": set()})
            e["uses"].add(kw)

    if not any_success:
        # Network down or nothing found — offline engine keeps Cook usable.
        return {"recipes": suggest_recipes(names), "source": "offline"}

    ranked = sorted(hits.values(), key=lambda x: -len(x["uses"]))
    total = max(1, len(ing_map))
    out = []
    for e in ranked[:12]:
        out.append({
            "id": e["id"],
            "title": e["title"],
            "thumb": e["thumb"],
            "uses": sorted(e["uses"]),
            "match": round(len(e["uses"]) / total, 2),
        })
    return {"recipes": out, "source": "online"}

def mealdb_lookup(meal_id):
    """Full recipe details for one meal id."""
    url = f"https://www.themealdb.com/api/json/v1/1/lookup.php?i={urllib.parse.quote(meal_id)}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "PantryTracker/1.0", "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                import gzip; raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8", errors="replace"))
        meals = data.get("meals") or []
        if not meals:
            return None
        m = meals[0]
        # Flatten the 20 ingredient/measure pairs into a clean list.
        ings = []
        for i in range(1, 21):
            ing = (m.get(f"strIngredient{i}") or "").strip()
            meas = (m.get(f"strMeasure{i}") or "").strip()
            if ing:
                ings.append({"ingredient": ing, "measure": meas})
        return {
            "id": m.get("idMeal"),
            "title": m.get("strMeal", ""),
            "thumb": m.get("strMealThumb", ""),
            "category": m.get("strCategory", ""),
            "area": m.get("strArea", ""),
            "instructions": m.get("strInstructions", ""),
            "youtube": m.get("strYoutube", ""),
            "source": m.get("strSource", ""),
            "ingredients": ings,
        }
    except Exception:
        return None

# ---------------------------------------------------------------- Routes

@app.route("/")
def index():
    return send_from_directory("templates", "index.html")

@app.route("/sw.js")
def service_worker():
    # Served from root scope so it can control the whole app.
    resp = send_from_directory("templates", "sw.js")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Content-Type"] = "application/javascript"
    return resp

@app.route("/manifest.json")
def manifest():
    return send_from_directory("templates", "manifest.json")

@app.route("/icon.svg")
def icon():
    return send_from_directory("templates", "icon.svg")

@app.route("/photos/<path:fn>")
def photos(fn):
    return send_from_directory(UPLOAD_DIR, fn)

@app.route("/api/items", methods=["GET"])
def list_items():
    db = get_db()
    cat = request.args.get("category")
    show_consumed = request.args.get("consumed", "0")
    filt = request.args.get("filter")  # 'expiring' -> at-risk groceries only
    q = "SELECT * FROM items WHERE 1=1"
    args = []
    if cat in ("grocery", "supply"):
        q += " AND category=?"
        args.append(cat)
    if show_consumed == "0":
        q += " AND consumed=0"
    q += " ORDER BY bought_at DESC, id DESC"
    rows = [row_to_dict(r) for r in db.execute(q, args).fetchall()]
    if filt == "expiring":
        risky = {"expired", "urgent", "soon"}
        rows = [r for r in rows if r["freshness"] in risky]
        order = {"expired": 0, "urgent": 1, "soon": 2}
        rows.sort(key=lambda r: (order.get(r["freshness"], 9), r["days_left"]))
    return jsonify(rows)

@app.route("/api/items", methods=["POST"])
def add_item():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Give the item a name."}), 400
    db = get_db()
    category = data.get("category", "grocery")
    bought = data.get("bought_at") or today()
    # Use the given best-by date, else estimate one from the food type.
    expires = (data.get("expires_at") or "").strip() or None
    if category == "grocery" and not expires:
        expires = estimate_expiry(name, data.get("subtype"), bought)
    cur = db.execute(
        """INSERT INTO items
           (name, category, subtype, upc, quantity, unit, photo,
            bought_at, expires_at, added_by, notes, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            name,
            category,
            (data.get("subtype") or "").strip() or None,
            (data.get("upc") or "").strip() or None,
            int(data.get("quantity", 1)),
            data.get("unit", "unit"),
            data.get("photo"),
            bought,
            expires,
            (data.get("added_by") or "house").strip(),
            (data.get("notes") or "").strip() or None,
            now_iso(),
        ),
    )
    db.commit()
    # Silently remember this UPC → product mapping so future scans auto-fill,
    # even for items the online database doesn't know. Upsert keeps it current
    # if the same barcode is later added with a corrected name/category.
    upc = (data.get("upc") or "").strip()
    if upc:
        db.execute(
            """INSERT INTO upc_catalog (upc, name, category, subtype, added_by, created_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(upc) DO UPDATE SET
                 name=excluded.name, category=excluded.category,
                 subtype=excluded.subtype""",
            (
                upc, name, category,
                (data.get("subtype") or "").strip() or None,
                (data.get("added_by") or "house").strip(),
                now_iso(),
            ),
        )
        db.commit()
    row = db.execute("SELECT * FROM items WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(row_to_dict(row)), 201

@app.route("/api/items/<int:item_id>", methods=["PATCH"])
def update_item(item_id):
    data = request.get_json(force=True)
    db = get_db()
    fields, args = [], []
    for k in ("name", "category", "subtype", "quantity", "unit",
              "notes", "consumed", "bought_at", "expires_at", "photo", "upc"):
        if k in data:
            fields.append(f"{k}=?")
            args.append(data[k])
    if not fields:
        return jsonify({"error": "Nothing to update."}), 400
    args.append(item_id)
    db.execute(f"UPDATE items SET {', '.join(fields)} WHERE id=?", args)
    db.commit()
    row = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return jsonify({"error": "Item not found."}), 404
    return jsonify(row_to_dict(row))

@app.route("/api/items/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    db = get_db()
    db.execute("DELETE FROM items WHERE id=?", (item_id,))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/upc/<upc>")
def upc_lookup(upc):
    # 1. Check the household's own learned catalog first — instant, offline,
    #    and covers store-brand/regional items the online DB never had.
    db = get_db()
    row = db.execute("SELECT * FROM upc_catalog WHERE upc=?", (upc,)).fetchone()
    if row:
        return jsonify({
            "name": row["name"],
            "subtype": row["subtype"] or "",
            "category": row["category"] or "grocery",
            "source": "catalog",
        })
    # 2. Fall back to the online lookup (Open Food Facts).
    info = lookup_upc(upc)
    if info:
        info["source"] = "online"
        return jsonify(info)
    # 3. Nothing found anywhere — caller will collect details and (on save)
    #    POST them back to /api/catalog so next time step 1 finds it.
    return jsonify({"error": "not found", "upc": upc}), 404

@app.route("/api/photo", methods=["POST"])
def upload_photo():
    """Accepts base64 data URL, stores a jpeg, returns filename."""
    data = request.get_json(force=True)
    b64 = data.get("image", "")
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    import base64
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return jsonify({"error": "bad image"}), 400
    fn = f"{int(time.time()*1000)}.jpg"
    with open(os.path.join(UPLOAD_DIR, fn), "wb") as f:
        f.write(raw)
    return jsonify({"photo": fn, "photo_url": f"/photos/{fn}"})

@app.route("/api/recipes")
def recipes():
    db = get_db()
    rows = db.execute(
        "SELECT name FROM items WHERE category='grocery' AND consumed=0"
    ).fetchall()
    names = [r["name"] for r in rows]
    if not names:
        return jsonify({"recipes": [], "source": "empty"})
    return jsonify(suggest_recipes_online(names))

@app.route("/api/recipe/<meal_id>")
def recipe_detail(meal_id):
    info = mealdb_lookup(meal_id)
    if info:
        # Flag which ingredients the household already has, for the UI.
        rows = get_db().execute(
            "SELECT name FROM items WHERE category='grocery' AND consumed=0"
        ).fetchall()
        hay = " ".join(r["name"].lower() for r in rows)
        for ing in info["ingredients"]:
            base = ing["ingredient"].lower()
            ing["have"] = any(w in hay for w in base.split() if len(w) > 2)
        return jsonify(info)
    return jsonify({"error": "not found"}), 404

# ---------------------------------------------------------------- Grocery list

@app.route("/api/list", methods=["GET"])
def list_get():
    """The shared shopping list. To-buy items first, then grabbed ones."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM grocery_list ORDER BY checked ASC, created_at ASC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/list", methods=["POST"])
def list_add():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Give the item a name."}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO grocery_list (name, added_by, created_at) VALUES (?,?,?)",
        (name, (data.get("added_by") or "someone").strip(), now_iso()),
    )
    db.commit()
    row = db.execute("SELECT * FROM grocery_list WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route("/api/list/<int:item_id>", methods=["PATCH"])
def list_update(item_id):
    """Toggle checked (grabbed) state; records who did it."""
    data = request.get_json(force=True)
    db = get_db()
    if "checked" in data:
        checked = 1 if data["checked"] else 0
        db.execute(
            "UPDATE grocery_list SET checked=?, checked_by=?, checked_at=? WHERE id=?",
            (
                checked,
                (data.get("checked_by") or "").strip() or None if checked else None,
                now_iso() if checked else None,
                item_id,
            ),
        )
        db.commit()
    row = db.execute("SELECT * FROM grocery_list WHERE id=?", (item_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    return jsonify(dict(row))

@app.route("/api/list/<int:item_id>", methods=["DELETE"])
def list_delete(item_id):
    db = get_db()
    db.execute("DELETE FROM grocery_list WHERE id=?", (item_id,))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/list/clear-checked", methods=["POST"])
def list_clear_checked():
    """Remove everything grabbed this trip — the 'done shopping' button."""
    db = get_db()
    n = db.execute("DELETE FROM grocery_list WHERE checked=1").rowcount
    db.commit()
    return jsonify({"cleared": n})

# ---------------------------------------------------------------- Categories

@app.route("/api/categories", methods=["GET"])
def categories_get():
    """Return category names, grouped by kind (grocery / supply)."""
    db = get_db()
    kind = request.args.get("kind")
    if kind in ("grocery", "supply"):
        rows = db.execute(
            "SELECT * FROM categories WHERE kind=? ORDER BY name COLLATE NOCASE", (kind,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    rows = db.execute("SELECT * FROM categories ORDER BY kind, name COLLATE NOCASE").fetchall()
    out = {"grocery": [], "supply": []}
    for r in rows:
        out.setdefault(r["kind"], []).append(dict(r))
    return jsonify(out)

@app.route("/api/categories", methods=["POST"])
def categories_add():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    kind = data.get("kind", "grocery")
    if not name:
        return jsonify({"error": "Give the category a name."}), 400
    if kind not in ("grocery", "supply"):
        kind = "grocery"
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO categories (name, kind, created_at) VALUES (?,?,?)",
            (name, kind, now_iso()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        # Already exists for this kind — return the existing one, not an error.
        row = db.execute(
            "SELECT * FROM categories WHERE name=? AND kind=?", (name, kind)
        ).fetchone()
        return jsonify(dict(row)), 200
    row = db.execute("SELECT * FROM categories WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route("/api/categories/<int:cat_id>", methods=["PATCH"])
def categories_rename(cat_id):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name can't be empty."}), 400
    db = get_db()
    try:
        db.execute("UPDATE categories SET name=? WHERE id=?", (name, cat_id))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "A category with that name already exists."}), 409
    row = db.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    return jsonify(dict(row))

@app.route("/api/categories/<int:cat_id>", methods=["DELETE"])
def categories_delete(cat_id):
    db = get_db()
    db.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    db.commit()
    return jsonify({"ok": True})

# ---------------------------------------------------------------- UPC catalog

@app.route("/api/catalog", methods=["POST"])
def catalog_add():
    """Explicitly save/update a UPC → product mapping (used when the user fills
    in an unknown scan). add_item also does this automatically; this endpoint
    lets the frontend save without necessarily adding stock."""
    data = request.get_json(force=True)
    upc = (data.get("upc") or "").strip()
    name = (data.get("name") or "").strip()
    if not upc or not name:
        return jsonify({"error": "Need both a UPC and a name."}), 400
    db = get_db()
    db.execute(
        """INSERT INTO upc_catalog (upc, name, category, subtype, added_by, created_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(upc) DO UPDATE SET
             name=excluded.name, category=excluded.category, subtype=excluded.subtype""",
        (
            upc, name, data.get("category", "grocery"),
            (data.get("subtype") or "").strip() or None,
            (data.get("added_by") or "house").strip(), now_iso(),
        ),
    )
    db.commit()
    return jsonify({"ok": True, "upc": upc}), 201

@app.route("/api/stats")
def stats():
    db = get_db()
    def scalar(q, a=()):
        return db.execute(q, a).fetchone()[0]
    # Count groceries at risk (expired, or best-by within 4 days).
    cutoff = (datetime.now().date() + timedelta(days=4)).strftime("%Y-%m-%d")
    expiring = scalar(
        """SELECT COUNT(*) FROM items
           WHERE category='grocery' AND consumed=0
             AND expires_at IS NOT NULL AND expires_at <= ?""",
        (cutoff,),
    )
    return jsonify({
        "groceries": scalar("SELECT COUNT(*) FROM items WHERE category='grocery' AND consumed=0"),
        "supplies": scalar("SELECT COUNT(*) FROM items WHERE category='supply' AND consumed=0"),
        "expiring": expiring,
        "total_items": scalar("SELECT COUNT(*) FROM items WHERE consumed=0"),
        "used_this_week": scalar(
            "SELECT COUNT(*) FROM items WHERE consumed=1 AND created_at >= date('now','-7 day')"
        ),
        "to_buy": scalar("SELECT COUNT(*) FROM grocery_list WHERE checked=0"),
    })

# Ensure the database schema exists whenever the app is loaded — including under
# gunicorn, which imports this module rather than running it as __main__. All
# schema statements use CREATE TABLE IF NOT EXISTS, so this is safe to run every
# start and never touches existing data. This means in-place code updates pick
# up new tables automatically on the next restart, with no manual migration step.
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
