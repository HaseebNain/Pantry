# Pantry — household inventory tracker

A self-hosted app the whole house uses from their phones. Tracks what's bought,
whether it's a **grocery** or a **house supply**, suggests **meals** from the
groceries on hand, and lets you **scan a UPC** or **snap a photo** for anything
without a barcode. Everything lives in a small database on your Raspberry Pi —
no cloud, no accounts.

## What's in the box

| File | Purpose |
|------|---------|
| `app.py` | Flask backend + SQLite database + UPC lookup + recipe engine |
| `templates/index.html` | The entire mobile web app (scanner, camera, all views) |
| `templates/sw.js` | Service worker — offline caching of the shelf |
| `templates/manifest.json` | Makes it installable as a home-screen app |
| `templates/icon.svg` | App icon |
| `setup.sh` | One-command install on the Pi |
| `make-cert.sh` | Generates the self-signed HTTPS certificate (for camera) |
| `run.sh` | Launcher — serves HTTPS if a cert exists, else HTTP |
| `pantry.service` | Auto-start on boot |
| `requirements.txt` | Python dependencies |
| `data/` | Where the database and photos are stored |
| `certs/` | HTTPS certificate (created by `make-cert.sh`; not shipped) |

## Install on the Raspberry Pi

1. Copy this whole folder to the Pi, e.g. into `/home/pi/pantry`.
2. Run:
   ```bash
   cd ~/pantry
   chmod +x setup.sh
   ./setup.sh
   ```
3. It prints an address like `http://192.168.1.42:8080`. Open that on any phone
   on your Wi-Fi. Use **Add to Home Screen** so it behaves like a native app.

> The `pantry.service` file assumes the folder is at `/home/pi/pantry` and the
> user is `pi`. If yours differs, edit the two paths and the `User=` line.

## Using it

- **Scan** — tap *Scan*, line the barcode up in the frame. Known products
  auto-fill their name and type (via the free Open Food Facts database). Unknown
  ones just drop the UPC in so you fill the rest.
- **Add** — for anything without a barcode. Snap a photo, name it, pick
  *Grocery* or *Supply*, set a type (Produce, Detergent, Paper towels…).
- **Groceries / Supplies tabs** — the shelf. Tap −/+ to adjust quantity; the ✓
  marks something used up (it leaves the active shelf but stays in history).
- **Cook tab** — meal ideas ranked by how many ingredients you already have,
  with the missing ones flagged.

## Checking the shelf from the store (remote access via Tailscale)

By default Pantry only works on your home Wi-Fi. To reach it from the grocery
store, add **Tailscale** — a free private network linking only your own devices.
Nothing is exposed to the public internet, no router ports are opened, and no
fixed IP is needed. As a bonus, Tailscale issues a *real, browser-trusted* HTTPS
certificate, so on the Tailscale address the phone camera works with **no
security warning** (unlike the self-signed LAN certificate below).

### Part 1 — Install Tailscale on the Pi

This Pi runs Raspberry Pi OS **Buster**, so use Tailscale's own Buster
repository (this doesn't depend on Debian's retired Buster mirrors, so the apt
errors seen elsewhere won't happen here):

```bash
curl -fsSL https://pkgs.tailscale.com/stable/raspbian/buster.noarmor.gpg | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/raspbian/buster.tailscale-keyring.list | sudo tee /etc/apt/sources.list.d/tailscale.list
sudo apt-get update
sudo apt-get install -y tailscale
```

If the first URL 404s (Tailscale has changed the key filename over time), use
the older key method instead — still valid on Buster:

```bash
curl -fsSL https://pkgs.tailscale.com/stable/raspbian/buster.asc | sudo apt-key add -
curl -fsSL https://pkgs.tailscale.com/stable/raspbian/buster.list | sudo tee /etc/apt/sources.list.d/tailscale.list
sudo apt-get update
sudo apt-get install -y tailscale
```

### Part 2 — Connect the Pi to your account

```bash
sudo tailscale up
```

This prints a URL. Open it in any browser, sign in (Google / GitHub / email —
the free personal plan is plenty), and the Pi joins your private network.
Confirm and note the Pi's name:

```bash
tailscale status
```

The Pi appears with a name like `raspberrypi`; its full address will be
`raspberrypi.your-tailnet.ts.net`.

### Part 3 — Enable HTTPS certificates (one-time, in the browser)

This is a switch in Tailscale's web console, **not** a command on the Pi,
because it applies to your whole account. Do it from any browser:

1. Go to **https://login.tailscale.com/admin/dns**
2. Sign in with the same account you used in Part 2.
3. On the **DNS** page, enable **MagicDNS** if it isn't already on.
4. Under **HTTPS Certificates**, click **Enable HTTPS**.
5. Acknowledge the notice that your device/tailnet names will be published on a
   public certificate ledger. This is normal for how trusted certificates work —
   it publishes only the *names*, never your data or access to the Pi.

After enabling, Tailscale may take a minute or two before it can issue
certificates. If Part 4 fails the first time, wait a moment and re-run it.

### Part 4 — Put Pantry on the trusted HTTPS address

Pantry already serves HTTPS on port 8443 (with its self-signed cert). Point
Tailscale Serve at it; Serve wraps it in the trusted certificate for phones:

```bash
sudo tailscale serve --bg --https=443 https+insecure://localhost:8443
```

- `https+insecure://localhost:8443` means "the local service uses a self-signed
  cert, that's expected" — Tailscale handles the trusted cert facing your phones.
- `--bg` runs it in the background **and auto-resumes after a reboot**, so this
  is a one-time command.

Check it:

```bash
tailscale serve status
```

It shows `https://raspberrypi.your-tailnet.ts.net/` proxying to Pantry.

### Part 5 — On each phone

Install the **Tailscale** app (App Store / Play Store), sign into the **same
account**, and leave it running in the background. Then open:

```
https://raspberrypi.your-tailnet.ts.net
```

(Use whatever name `tailscale serve status` printed.) That one URL works
identically at home and at the store, on Wi-Fi or cellular — camera scanning
included, with no certificate warning. Add it to the home screen and it's your
single address for everything.

> **This supersedes the self-signed LAN warning.** On the `.ts.net` address you
> won't see the "not private" prompt — that only applied to the raw
> `https://<pi-ip>:8443` address. You can still use the LAN address at home if
> Tailscale is ever off, but the `.ts.net` one is simpler to always use.
>
> **Free tier** covers up to 100 devices — far more than a household needs.
>
> Tailscale only adds a network layer and forwards one port to Pantry. It does
> not change anything about other services on the Pi.

## Offline support

Pantry is a PWA with a service worker, so the store's dead spots don't leave you
stranded:

- The app shell and your **last-loaded inventory are cached on the phone**. Open
  Pantry with no signal and it still shows the shelf, with an amber banner
  reading *"Offline — showing last synced"* and how long ago that was.
- While offline, the quantity, ✓, Scan and Add controls are **dimmed** — changes
  need a live connection to the Pi, so the app tells you rather than silently
  losing edits.
- The moment the phone reconnects (e.g. you walk back in the door), it
  **re-syncs automatically** and the banner clears.

This all works after the *first* successful load on a device — the phone needs
to have seen the shelf online at least once to cache it.


## Freshness — knowing what's about to go bad

Every grocery gets a **best-by date** so you can see at a glance what to use
soon. There are two ways it's set:

- **Automatic estimate.** When you add a grocery, Pantry guesses a shelf life
  from what it is — fresh fish ~2 days, leafy greens ~5, dairy ~1 week, root veg
  ~3 weeks, canned/dry goods ~1 year. You get a sensible date for free.
- **Manual best-by.** The add screen has an optional *Best by* field. Type what's
  printed on the package (or your own judgement) and it overrides the estimate.

Supplies don't spoil, so they skip this entirely.

**How it shows up:**

- Each grocery card's **left edge is colour-coded** — green (fresh), amber (use
  within ~4 days), deep-amber (use today / tomorrow), red (expired). Fresh items
  stay quiet; anything needing attention gets a small badge like *"2 days left"*
  or *"expired 3d ago"*.
- The header's **"Use soon"** counter shows how many groceries are at risk, and
  glows amber when any are. Tap it — or the **Use soon** tab — for a focused list
  of just the at-risk items, sorted most-urgent first. That's the list to glance
  at before deciding what to cook.

**Tuning the estimates:** the shelf-life table lives in `SHELF_LIFE` near the top
of `app.py`, as `(["keyword", "matches"], days_until_expiry)`. Add or adjust
entries to match how your household actually shops and stores food. Unknown
groceries default to 14 days.

## Shared shopping list

The **List** tab is a shared shopping list for the whole house — synced through
the Pi, so everyone sees the same list on their own phone in real time. Add milk
on yours, and it's on your partner's list instantly.

- **Who added what.** The first time someone opens the List on a device, it asks
  for a name (just once — it's remembered on that phone). Everything they add is
  tagged *"added by <name>"*, and when they check something off while shopping it
  records *"grabbed by <name>"*. No accounts or passwords — just a name so the
  household knows who wanted what. Tap *change* to update it.
- **Adding items.** Type freely (e.g. "milk") and tap Add or press Enter.
- **Shopping.** Tap the checkbox to mark an item grabbed; it moves to an *In the
  cart* section, greyed out, so you can see what's already in the trolley without
  losing the record of who asked for it.
- **After the trip.** Tap *Clear grabbed items* to wipe everything you checked
  off, leaving anything still to-buy for next time.

Like the rest of Pantry, the list lives in `data/pantry.db`, so it's covered by
the same backup and survives updates.

## Learned UPC catalog & categories

Pantry gets smarter as your household uses it — two connected features:

**A local UPC catalog.** When you scan a barcode, Pantry checks three places in
order: (1) your own saved catalog, (2) the online Open Food Facts database, then
(3) if neither knows it, you fill in the details yourself. Whenever you add an
item that has a UPC, that barcode → product mapping is saved automatically. The
next time anyone scans that same barcode — on any phone — it fills in instantly,
even offline, and even for store-brand or regional items the online database
never had. Over time you build a private catalog matched exactly to what your
house buys. (Saving is silent; correcting an item's name and re-adding it under
the same barcode updates the catalog.)

**Category dropdowns you control.** The category/type field is a dropdown, seeded
with sensible defaults — separate lists for groceries (Produce, Dairy, Meat,
Frozen, Pantry…) and supplies (Detergent, Paper goods, Cleaning, Toiletries…).
Pick *➕ Add new category* to create one on the spot, or *✏️ Manage categories*
to rename or delete any of them. New categories are saved to their own catalog
and appear in the dropdown for everyone, from then on. The defaults are seeded
only once, so your edits and deletions are never overwritten by a restart.

## Cook — recipe suggestions

The **Cook** tab suggests real recipes based on what's on your shelf, using
TheMealDB (https://www.themealdb.com) — a free online recipe database, no API key
needed. For each grocery you have, Pantry searches the database and ranks meals
by **how many of your ingredients they use**, so the recipe drawing on the most
of what you already have rises to the top. Tap a suggestion for the full recipe:
photo, ingredient list (the ones you already have are ticked green), the method,
and a video link where one exists. For ingredients you **don't** have, each shows
a **+ List** button, and there's an **Add all missing to list** button at the top
— one tap sends what you're missing to the shared shopping list, tagged with your
name.

Notes:
- It needs internet on the Pi (same connection the UPC lookup uses). If the
  recipe service is unreachable, Cook falls back to a small built-in list so it's
  never empty.
- Matching keys off ingredient words in item names, so plain names ("Roma
  tomatoes", "chicken breast") match better than heavily branded ones.
- The free key returns single-ingredient matches, which Pantry combines across
  your groceries — no key or payment required.

## Camera scanning & HTTPS

Phone browsers only allow camera access over `https://` (or `localhost`), so
over plain `http://<pi-ip>:8080` the barcode scanner reports "camera
unavailable." Pantry solves this with a **self-signed HTTPS certificate**, set
up automatically by `setup.sh`. After install, reach Pantry at:

    https://<hostname>.local:8443     (preferred — survives the Pi's IP changing)
    https://<pi-ip>:8443              (if .local doesn't resolve on your network)

The certificate covers the Pi's hostname *and* its current IP addresses, so it
keeps working even if the router hands out a different IP later.

**The one-time warning:** because the certificate is self-signed (not issued by
a public authority), each phone shows a "your connection is not private" notice
the first time. Tap **Advanced → Proceed** (wording varies by browser). That's a
one-time step per phone; afterwards the camera scanner works normally. This is
expected and safe — the "warning" only means the certificate wasn't bought from
a certificate authority, not that anything is wrong on your own network.

**Regenerating the certificate** (e.g. if you rename the Pi):

```bash
./make-cert.sh
sudo systemctl restart pantry
```

If no certificate is present, Pantry falls back to plain HTTP on port 8080 —
everything works except camera scanning, where you can use the *Type it instead*
button or the photo fallback.

## Updating Pantry (adding features / editing code)

The golden rule: **your code and your data live in different places, and you only
ever overwrite code.**

| Safe to overwrite | Never overwrite (your stuff) |
|-------------------|------------------------------|
| `app.py` | `data/pantry.db` — all your items |
| `templates/` (`index.html`, `sw.js`, …) | `data/photos/` — item photos |
| `*.sh`, `pantry.service`, `requirements.txt` | `certs/` — your HTTPS certificate |

As long as you don't touch the right-hand column, you can't lose your inventory.

### The normal workflow (editing a file on the Pi)

Most changes — a new recipe, a tweak to `app.py`, an edit to the UI — are just:

```bash
# 1. edit the file (e.g. nano app.py)
# 2. restart the service so it re-reads the code:
sudo systemctl restart pantry
```

That's it. No shutdown ritual, no database migration by hand. `gunicorn` loads
the code fresh on every start, so a restart is all it takes to pick up changes
to `app.py`. Your database is a separate file and is never touched by a restart.

- **Backend changes** (`app.py`) → require the `systemctl restart` above.
- **Frontend changes** (`templates/index.html`, `sw.js`) → served straight from
  disk, so they appear on the next browser refresh even *without* a restart.
  But see the service-worker note below — phones cache the frontend.

### Pasting in a whole new version (the careful way)

If you're dropping in a fresh copy of the project (e.g. a new `pantry.zip` from a
later session), **do not unzip it straight over your folder** — that would
clobber `data/pantry.db`. Instead, unzip elsewhere and copy only the code across:

```bash
# unzip the new version somewhere separate
cd ~
unzip pantry.zip -d pantry-new       # creates ~/pantry-new/pantry

# copy ONLY code files over your live folder (note: no data/, no certs/)
cp ~/pantry-new/pantry/app.py            ~/pantry/
cp -r ~/pantry-new/pantry/templates      ~/pantry/
cp ~/pantry-new/pantry/*.sh              ~/pantry/
cp ~/pantry-new/pantry/requirements.txt  ~/pantry/
cp ~/pantry-new/pantry/pantry.service    ~/pantry/    # only if it changed

# restart
sudo systemctl restart pantry
```

`data/` and `certs/` in your live folder are left untouched, so your items and
HTTPS cert survive. If `requirements.txt` changed, also refresh dependencies:

```bash
cd ~/pantry && ./venv/bin/pip install -r requirements.txt
sudo systemctl restart pantry
```

### Always back up first (one file)

Before any update, copy the database somewhere safe. The whole inventory is a
single file, so this is instant:

```bash
cp ~/pantry/data/pantry.db ~/pantry-backup-$(date +%Y%m%d).db
```

If an update ever goes wrong, stop the service, copy that file back, and restart:

```bash
sudo systemctl stop pantry
cp ~/pantry-backup-YYYYMMDD.db ~/pantry/data/pantry.db
sudo systemctl start pantry
```

### The service-worker gotcha (frontend changes)

Because Pantry is an installed app, each phone **caches the frontend** for
offline use. After you change `index.html`, a phone may keep showing the old
version until its cache refreshes. To force every phone to pick up the new UI,
bump the cache version in `templates/sw.js` — change both lines:

```js
const SHELL = "pantry-shell-v3";   // → bump to v4, v5, …
const DATA  = "pantry-data-v3";    // → bump to match
```

The service worker treats a new version name as a fresh cache, so phones
re-download the updated files on their next visit. (Current version: **v3**.)
You don't need this for backend-only changes.

### Handy service commands

```bash
sudo systemctl restart pantry      # apply code changes
sudo systemctl stop pantry         # stop it
sudo systemctl start pantry        # start it
sudo systemctl status pantry       # is it running? recent logs
journalctl -u pantry -f            # live logs (Ctrl-C to exit) — great for debugging
```

If a change breaks startup, `sudo systemctl status pantry` and `journalctl -u
pantry -f` will show the Python error, so you can fix `app.py` and restart.

## Notes & tweaks

- **Recipes** live in the `RECIPES` list in `app.py` — add your household's
  favourites as `("Meal name", ["ingredient", "keywords"])`.
- **Backups** — the whole state is one file: `data/pantry.db`. Copy it anywhere.
- **Ports** — with a certificate, Pantry serves **both** at once: HTTPS on
  `8443` (phones, Tailscale, camera scanning) **and** plain HTTP on `8080` (home
  computers on the LAN, no cert warning). Without a certificate it's HTTP on
  `8080` only. Both bind to `0.0.0.0`, so every device on the LAN can reach the
  Pi. Home computers just use `http://<pi-ip>:8080`; phones use the Tailscale
  `https://…ts.net` address.
- **Household setup** — two companion guides ship alongside this README:
  `HOUSEHOLD-SETUP.md` (hand this to each family member — how to get Pantry on
  their phone) and `HOST-SHARING-GUIDE.md` (for you, the Pi owner — how to invite
  them via Tailscale device-sharing so nobody shares a login).

## Running by hand (dev / testing)

```bash
./run.sh                       # HTTPS on 8443 if certs/ exists, else HTTP on 8080
./venv/bin/python app.py       # plain HTTP on 8080 (simplest, no TLS)
```
