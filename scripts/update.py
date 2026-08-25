#!/usr/bin/env python3
"""Daily updater for 2024michael.com.

For each athlete with a refresh token, pulls activities since their last check,
scans segment_efforts for the tracked segments, updates rolling PRs and
attempt counts in data/state.json, then regenerates data.js for the site.

All four riders (Ali, Jake, Randee, Michael) are tracked live. The "2024 Michael"
branding on the site is a gimmick, not a frozen data set.
"""
import json, os, sys, time, datetime, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "data", "state.json")
META_PATH = os.path.join(ROOT, "data", "meta.json")
DATA_JS_PATH = os.path.join(ROOT, "data.js")

API = "https://www.strava.com/api/v3"
_meta = json.load(open(META_PATH))
TRACKED = {s["id"] for s in _meta["segments"]}
OVERLAP = 3 * 86400  # re-scan 3 days back to catch late uploads
PWINDOWS = [300, 600, 1200, 1800, 3600]  # power best-effort windows (sec)

def http(url, data=None, token=None):
    req = urllib.request.Request(url, data=data)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def refresh_access_token(client_id, client_secret, refresh_token):
    body = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": client_secret,
        "grant_type": "refresh_token", "refresh_token": refresh_token,
    }).encode()
    return http("https://www.strava.com/oauth/token", data=body)

def fmt_time(sec):
    m, s = divmod(int(sec), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def fmt_date(iso):
    d = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return d.strftime("%b %-d, %Y") if os.name != "nt" else d.strftime("%b %d, %Y").replace(" 0", " ")

def best_window_avgs(times, watts, windows):
    """Best average watts for each window, from time/watts streams."""
    if not times or not watts or len(times) != len(watts):
        return {}
    dur = int(times[-1])
    if dur <= 0:
        return {}
    series = [0] * (dur + 1)
    last, ptr = 0, 0
    for t in range(dur + 1):
        while ptr < len(times) and times[ptr] <= t:
            if watts[ptr] is not None:
                last = watts[ptr]
            ptr += 1
        series[t] = last
    prefix = [0]
    for v in series:
        prefix.append(prefix[-1] + v)
    n = len(series)
    out = {}
    for w in windows:
        if n < w:
            continue
        best = max(prefix[i + w] - prefix[i] for i in range(n - w + 1))
        if best > 0:
            out[w] = round(best / w)
    return out

def main():
    cid = os.environ["STRAVA_CLIENT_ID"]
    csec = os.environ["STRAVA_CLIENT_SECRET"]
    tokens = {
        "ali": os.environ.get("STRAVA_REFRESH_ALI", ""),
        "jake": os.environ.get("STRAVA_REFRESH_JAKE", ""),
        "randee": os.environ.get("STRAVA_REFRESH_RANDEE", ""),
        "michael": os.environ.get("STRAVA_REFRESH_MICHAEL", ""),
    }

    state = json.load(open(STATE_PATH))
    changed = False
    summary = []

    for key, ath in state["athletes"].items():
        rt = tokens.get(key)
        if not rt:
            print(f"[{key}] no refresh token configured - skipping")
            continue
        try:
            tok = refresh_access_token(cid, csec, rt)
        except Exception as e:
            print(f"[{key}] token refresh FAILED: {e}", file=sys.stderr)
            continue
        access = tok["access_token"]
        since = max(0, int(ath.get("last_epoch", 0)) - OVERLAP)
        now = int(time.time())

        # list activities since last check (paginated)
        acts, page = [], 1
        while True:
            batch = http(f"{API}/athlete/activities?after={since}&per_page=100&page={page}", token=access)
            acts.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        print(f"[{key}] {len(acts)} activities since {since}")

        for a in acts:
            if a.get("type") not in ("Ride", "VirtualRide", "GravelRide", "MountainBikeRide"):
                continue
            try:
                detail = http(f"{API}/activities/{a['id']}?include_all_efforts=true", token=access)
            except Exception as e:
                print(f"[{key}] activity {a['id']} fetch failed: {e}", file=sys.stderr)
                continue

            # ---- global exclusions: no e-bikes, no Peloton, for segments AND power ----
            # Ali's rule: e-bike and Peloton rides do not count for anything.
            # Zwift and other smart trainer rides arrive as VirtualRide with
            # device_watts and are deliberately allowed.
            dev = str(detail.get("device_name") or "").lower()
            if detail.get("type") == "EBikeRide" or "peloton" in dev:
                print(f"[{key}] skipping {a['id']}: e-bike or Peloton")
                time.sleep(1)
                continue
            for eff in detail.get("segment_efforts", []):
                sid = eff.get("segment", {}).get("id")
                if sid not in TRACKED:
                    continue
                sid_s = str(sid)
                sec = int(eff["elapsed_time"])
                # attempts: increment only if we track an absolute count for this athlete
                if ath["attempts"].get(sid_s) is not None:
                    ath["attempts"][sid_s] += 1
                    changed = True
                best = ath["bests"].get(sid_s)
                if best is None or sec < best["sec"]:
                    watts = eff.get("average_watts")
                    ath["bests"][sid_s] = {
                        "sec": sec, "time": fmt_time(sec),
                        "date": fmt_date(eff.get("start_date_local", a.get("start_date_local", ""))),
                        "watts": round(watts) if watts else None,
                    }
                    changed = True
                    summary.append(f"{ath['display']} new PR on segment {sid}: {fmt_time(sec)}")

            # ---- power bests: real meters only (e-bike/Peloton already excluded above) ----
            try:
                dev = str(detail.get("device_name") or "").lower()
                if (detail.get("device_watts") and detail.get("type") != "EBikeRide"
                        and "peloton" not in dev):
                    sj = http(f"{API}/activities/{a['id']}/streams?keys=time,watts&key_by_type=true", token=access)
                    tt = (sj.get("time") or {}).get("data") or []
                    ww = (sj.get("watts") or {}).get("data") or []
                    bests = best_window_avgs(tt, ww, PWINDOWS)
                    pw = ath.setdefault("power", {})
                    for w, val in bests.items():
                        k = str(w)
                        if val > int(pw.get(k) or 0):
                            pw[k] = val
                            changed = True
                            summary.append(f"{ath['display']} new {w//60} min power: {val} W")
            except Exception as e:
                print(f"[{key}] power calc failed for {a['id']}: {e}", file=sys.stderr)
            time.sleep(1)  # be polite to rate limits

        if ath.get("last_epoch") != now:
            ath["last_epoch"] = now
            changed = True

    if changed:
        state["updated"] = datetime.date.today().strftime("%b %d, %Y").replace(" 0", " ")
    json.dump(state, open(STATE_PATH, "w"), indent=2)

    # regenerate data.js regardless (cheap, idempotent)
    meta = json.load(open(META_PATH))
    segs_out = []
    for seg in meta["segments"]:
        sid_s = str(seg["id"])
        riders = []
        for key, ath in state["athletes"].items():
            b = ath["bests"].get(sid_s)
            att = ath["attempts"].get(sid_s)
            if b:
                riders.append({"name": ath["display"], "sec": b["sec"], "time": b["time"],
                               "date": b["date"], "watts": b["watts"], "attempts": att})
            else:
                riders.append({"name": ath["display"], "sec": None, "time": "—",
                               "date": "never attempted", "watts": None, "attempts": att})
        riders.sort(key=lambda r: (r["sec"] is None, r["sec"] if r["sec"] is not None else 0))
        seg_out = dict(seg)
        seg_out["riders"] = riders
        seg_out["pl"] = meta["polylines"][sid_s]
        segs_out.append(seg_out)

    power_out = {}
    for key, ath in state["athletes"].items():
        if ath.get("power"):
            power_out[ath["display"]] = ath["power"]
    payload = {"updated": state["updated"], "segs": segs_out, "power": power_out}
    with open(DATA_JS_PATH, "w") as f:
        f.write("window.SITE_DATA = ")
        json.dump(payload, f, separators=(",", ":"))
        f.write(";\n")

    print("SUMMARY:", "; ".join(summary) if summary else "no PR changes")

if __name__ == "__main__":
    main()
