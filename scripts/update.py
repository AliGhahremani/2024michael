#!/usr/bin/env python3
"""Daily updater for 2024michael.com.

For each athlete with a refresh token, pulls activities since their last check,
scans segment_efforts for the six tracked segments, updates rolling PRs and
attempt counts in data/state.json, then regenerates data.js for the site.

Michael's benchmark times are frozen (michael_frozen in state.json) - by design.
"""
import json, os, sys, time, datetime, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "data", "state.json")
META_PATH = os.path.join(ROOT, "data", "meta.json")
DATA_JS_PATH = os.path.join(ROOT, "data.js")

API = "https://www.strava.com/api/v3"
TRACKED = {649404, 7855869, 913750, 618874, 633514, 706732}
OVERLAP = 3 * 86400  # re-scan 3 days back to catch late uploads

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
    return d.strftime("%b %d, %Y").replace(" 0", " ")

def main():
    cid = os.environ["STRAVA_CLIENT_ID"]
    csec = os.environ["STRAVA_CLIENT_SECRET"]
    tokens = {
        "ali": os.environ.get("STRAVA_REFRESH_ALI", ""),
        "jake": os.environ.get("STRAVA_REFRESH_JAKE", ""),
        "randee": os.environ.get("STRAVA_REFRESH_RANDEE", ""),
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

        acts, page = [], 1
        while True:
            batch = http(f"{API}/athlete/activities?after={since}&per_page=100&page={page}", token=access)
            acts.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        print(f"[{key}] {len(acts)} activities since {since}")

        for a in acts:
            if a.get("type") not in ("Ride", "VirtualRide", "EBikeRide", "GravelRide", "MountainBikeRide"):
                continue
            try:
                detail = http(f"{API}/activities/{a['id']}?include_all_efforts=true", token=access)
            except Exception as e:
                print(f"[{key}] activity {a['id']} fetch failed: {e}", file=sys.stderr)
                continue
            for eff in detail.get("segment_efforts", []):
                sid = eff.get("segment", {}).get("id")
                if sid not in TRACKED:
                    continue
                sid_s = str(sid)
                sec = int(eff["elapsed_time"])
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
            time.sleep(1)

        if ath.get("last_epoch") != now:
            ath["last_epoch"] = now
            changed = True

    if changed:
        state["updated"] = datetime.date.today().strftime("%b %d, %Y").replace(" 0", " ")
    json.dump(state, open(STATE_PATH, "w"), indent=2)

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
                riders.append({"name": ath["display"], "sec": None, "time": "\u2014",
                               "date": "never attempted", "watts": None, "attempts": att})
        m = state["michael_frozen"][sid_s]
        riders.append({"name": "Michael", "sec": m["sec"], "time": m["time"],
                       "date": m["date"], "watts": m["watts"], "attempts": None})
        riders.sort(key=lambda r: (r["sec"] is None, r["sec"] if r["sec"] is not None else 0))
        seg_out = dict(seg)
        seg_out["riders"] = riders
        seg_out["pl"] = meta["polylines"][sid_s]
        segs_out.append(seg_out)

    payload = {"updated": state["updated"], "segs": segs_out}
    with open(DATA_JS_PATH, "w") as f:
        f.write("window.SITE_DATA = ")
        json.dump(payload, f, separators=(",", ":"))
        f.write(";\n")

    print("SUMMARY:", "; ".join(summary) if summary else "no PR changes")

if __name__ == "__main__":
    main()
