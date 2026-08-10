# Pantry — how to invite the household (for the Pi owner)

You've got Tailscale working on the Pi. Now you want to let family members reach
Pantry from their phones **without** the confusion of everyone logging into your
account. The clean way is **device sharing**: each person makes their *own* free
Tailscale account, and you share just the Pi with them. They see only the Pi —
never your other devices — and you never juggle logins.

This is simpler and safer than adding them as "users" on your tailnet, and it
isn't limited by the 3-user cap on the free plan.

---

## One-time: share the Pi with each person

1. Go to the **admin console**: https://login.tailscale.com/admin/machines
2. Find your Pi in the list (e.g. `raspberrypi`).
3. Click the **⋮** menu on the right of that row → **Share…**
4. In the dialog, use **Copy invite link** (or **Share by email** to send it
   straight to them).
   - Choose a **single-use** link per person if you want tight control, or a
     **reusable** link you can send to everyone. Either expires in 30 days if
     unused.
5. Send that link to the family member (text, email, whatever's easy).

That's it on your end. Repeat the copy-link step for each person, or reuse one
reusable link for all of them.

## What they do

Send them the **HOUSEHOLD-SETUP.md** guide (the companion to this file). In
short, they:
1. Install the Tailscale app.
2. Tap your invite link and sign in with **any** account of their own.
3. Turn Tailscale on.
4. Open the Pantry `.ts.net` address and add it to their home screen.

Because the Pi is *shared* (not owned by them), it's automatically quarantined:
their phone can reach Pantry, but nothing on their device is exposed to you, and
nothing of yours is exposed to them.

## The one address everyone uses

Give everyone this (from `tailscale serve status` on the Pi):

    https://raspberrypi.tailXXXXXX.ts.net

It works for every shared user, on any network, at home or away.

---

## Reminder: the two ways in

- **Phones / away from home:** the `.ts.net` HTTPS address above (needs the
  Tailscale app). Camera scanning works here.
- **Home computers on the Wi-Fi:** the plain local address `http://<pi-ip>:8080`
  — no app, no Tailscale needed. (Find the Pi's IP with `hostname -I` on the Pi.)

Both are served at the same time by Pantry, so you don't have to choose.

## If you'd rather not use Tailscale at all

Tailscale is the recommended path because it's private and needs no router
changes. But if you only ever need Pantry **inside the house**, you can skip
Tailscale entirely: everyone (phones included) just uses `http://<pi-ip>:8080`
on the home Wi-Fi. The only thing you lose is (a) access from outside the house
and (b) camera scanning on phones (which needs HTTPS). For a purely-at-home
setup, that's a perfectly fine, zero-setup option.
