# Pantry — setting it up on your phone

This is for **everyone in the house**. It takes about 5 minutes, once.

When you're done, you'll have Pantry on your phone that works **everywhere** —
at home and at the store — with a shortcut on your home screen like a normal app.

There are two ways to use Pantry, and you can use both:

- **On a home computer** (at home only): just open a web browser and go to the
  Pi's address. Nothing to install. *(The person who runs the Pi will give you
  this address — it looks like `http://192.168.x.x:8080`.)*
- **On your phone** (works anywhere, including the store): follow the steps
  below once. This needs a free app called Tailscale, which is what lets your
  phone reach the house's Pantry when you're away from home.

---

## Phone setup — do this once

### Step 1 — Get the invite link
The person who runs the Pi will send you a **Tailscale invite link** (by text,
email, or a message). It'll look something like:

    https://login.tailscale.com/admin/invite/xxxxxxxx

Don't click it yet — read Step 2 first so you know what to expect.

### Step 2 — Install the Tailscale app

**iPhone:**
1. Open the **App Store**.
2. Search for **Tailscale** and install it (it's free).

**Android:**
1. Open the **Play Store**.
2. Search for **Tailscale** and install it (it's free).

### Step 3 — Open the invite link and sign in
1. Now tap the **invite link** you were sent.
2. It opens Tailscale and asks you to sign in. Choose **any** option —
   Google, Apple, Microsoft, or email. Use whatever's easiest for you; it
   becomes your own private account. **You do not need the same login as anyone
   else in the house.**
3. Accept the invitation when prompted. This connects you to the house's Pi
   (and *only* the Pi — you won't see anyone's personal devices, and they won't
   see yours).

### Step 4 — Turn Tailscale ON
In the Tailscale app, flip the switch to **Connected**. That's it — leave the
app installed and let it run in the background. You don't have to open it again.

### Step 5 — Open Pantry and add it to your home screen
1. Open **Safari** (iPhone) or **Chrome** (Android).
2. Go to the Pantry address the Pi owner gives you. It looks like:

       https://raspberrypi.tailXXXXXX.ts.net

3. Add it to your home screen so it opens like an app:
   - **iPhone:** tap the **Share** button (box with an arrow) → **Add to Home
     Screen**.
   - **Android:** tap the **⋮** menu → **Add to Home screen**.
4. Tap the new Pantry icon any time — at home or out shopping. Done!

---

## Everyday use

- **The first time you open the List tab**, Pantry asks your name. Type it once;
  it's remembered on your phone. Everything you add to the shopping list shows up
  as "added by <you>."
- **Scanning:** tap Scan and point the camera at a barcode. The first time, your
  phone asks permission to use the camera — tap **Allow**.
- **It works at the store** because Tailscale is running in the background. If
  Pantry ever won't load while you're out, open the Tailscale app and check the
  switch is **Connected**.

---

## Troubleshooting

**"It won't load."**
Open the Tailscale app and make sure it says **Connected**. If it's off, flip it
on. That's the #1 fix.

**"The camera is black or won't turn on."**
Fully close the browser (swipe it away) and reopen Pantry. If it still won't ask
for camera permission, check your phone's Settings → (Safari or Chrome) →
Camera, and allow it for the Pantry site.

**"I want to use it on my laptop at home."**
On the home Wi-Fi, just open a browser to the Pi's local address
(`http://192.168.x.x:8080` — ask the Pi owner for the exact one). No app needed
on computers that stay home.
