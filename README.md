# 2024michael.com

Are you stronger than 2024 Michael? A self-updating standings site.

- **Site**: `index.html` + `data.js` (static, hosted on GitHub Pages)
- **Updater**: GitHub Actions runs `scripts/update.py` daily at 8:00 AM PDT (15:00 UTC; becomes 7:00 AM in winter — edit the cron in `.github/workflows/update.yml` if you care)
- **Data**: each rider's own Strava account authorizes the app once; the script pulls only their *own* new activities via the official Strava API and updates rolling PRs. **Michael's benchmark times are frozen by design — he never needs to authorize anything.**

## One-time setup (Ali)

### 1. Create a Strava API application
Go to https://www.strava.com/settings/api (logged in as you). Fill in:
- Application name: `2024michael`
- Website: `https://2024michael.com` (or anything)
- Authorization Callback Domain: `localhost`

Note the **Client ID** and **Client Secret**.

### 2. Create the GitHub repo
1. Create a new repo (public or private both work), e.g. `2024michael`.
2. Push this folder's contents to it.
3. Settings → Pages → Source: "Deploy from a branch" → branch `main`, folder `/ (root)`. Your site goes live at `https://<user>.github.io/2024michael/`.
4. Settings → Actions → General → Workflow permissions → "Read and write permissions" (needed so the bot can commit updated data).

### 3. Add secrets
Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `STRAVA_CLIENT_ID` | from step 1 |
| `STRAVA_CLIENT_SECRET` | from step 1 |
| `STRAVA_REFRESH_ALI` | from step 4 |
| `STRAVA_REFRESH_JAKE` | from step 4 |
| `STRAVA_REFRESH_RANDEE` | from step 4 |

### 4. Get refresh tokens (you, Jake, Randee)
Send each rider this link (replace `CLIENT_ID`):

```
https://www.strava.com/oauth/authorize?client_id=CLIENT_ID&response_type=code&redirect_uri=http://localhost&approval_prompt=force&scope=activity:read_all
```

They click **Authorize**, land on a broken `localhost` page (expected), and immediately send you the **full URL from the address bar** (the code in it expires within minutes). Then run:

```
python scripts/exchange_token.py CLIENT_ID CLIENT_SECRET "PASTED_URL_OR_CODE"
```

It prints the athlete's refresh token — store it as that rider's secret. Refresh tokens are long-lived; this is one-time per rider.

### 5. Test
Actions tab → "Update standings" → **Run workflow**. Green check = working. The site's "Last updated" date in the footer confirms it.

## How updates work
- The script fetches each authorized rider's activities since the last run (with a 3-day overlap for late uploads), scans their segment efforts on the six tracked segments, and updates `data/state.json` + `data.js`. New PRs and attempt counts flow to the page automatically; standings and YES/NO badges are computed client-side.
- Riders who haven't authorized simply keep their baseline times (scraped Aug 22, 2026).
- Attempt counts only accumulate where a baseline count exists (currently Ali only). Jake/Randee show "—" — Strava doesn't expose historical counts without scanning their full history (possible later; edit `update.py` if you want a full backfill).

## Pointing 2024michael.com at it (later)
Buy the domain, then: repo Settings → Pages → Custom domain → `2024michael.com`, and add the DNS records GitHub shows you at your registrar. HTTPS is automatic.
