Vercel Connection Checklist
--------------------------

1) Prepare repository
   - Ensure the repo is committed and pushed to GitHub.
   - Confirm the branch you want to deploy (e.g., `main`).

2) Vercel project import
   - Go to https://vercel.com/new
   - Select your GitHub account and choose the repo.
   - Set **Root Directory** to `app.py` (because code lives under `app.py/`).
   - Framework Preset: `Other` (we use Python serverless functions).

3) Build & Output settings
   - No build command required for Python serverless functions.
   - Make sure `vercel.json` is present at project root (we added it).

4) Environment variables (Project > Settings > Environment Variables)
   - `DATABASE_URL` = your Postgres connection string
   - `SECRET_KEY` = Flask secret
   - `QR_SECRET` = (optional) secret used by QR generator
   - Any other values from your `.env`

5) Deploy & verify
   - After import, trigger a deployment (Vercel does this automatically on import).
   - Verify health: `https://<your-deployment>/api/health`
   - Verify API: basic endpoint like `https://<your-deployment>/api/products`

6) Optional: Use Vercel CLI to link and deploy from local
   - Install CLI: `npm i -g vercel`
   - Login: `vercel login`
   - From repo root run: `vercel link` and choose the existing project
   - Deploy: `vercel --prod`

Notes
- WebSockets are not supported on Vercel serverless functions; the app uses HTTP fallbacks for real-time events.
- For persistent sockets use Render/Railway/Heroku or a managed realtime provider.
