Vercel Connection Checklist
--------------------------

1) Prepare repository
   - Ensure this repo is committed and pushed to GitHub.

2) Vercel project import
   - Go to https://vercel.com/new
   - Select your GitHub account and choose the repo.
   - Set **Root Directory** to repository root.
   - Framework Preset: `Other`.

3) Vercel routing
   - `vercel.json` routes:
     - `/api/health` -> `api/health.py`
     - `/(.*)` -> `api/index.py`

4) Environment variables (Project > Settings > Environment Variables)
   - `DATABASE_URL` = your Postgres connection string
   - `SECRET_KEY` = Flask secret
   - `QR_SECRET` = optional secret used by QR generator

5) Deploy & verify
   - Verify health: `https://<deployment>/api/health`
   - Verify API: `https://<deployment>/api/products`

6) Optional: Vercel CLI
   - Install CLI: `npm i -g vercel`
   - Login: `vercel login`
   - Link project: `vercel link`
   - Deploy production: `vercel --prod`

Notes
- WebSockets are not supported on Vercel serverless functions.
- For persistent sockets use a platform with long-lived connections.
