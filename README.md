# kingdompublishers

## Vercel deployment (clean setup)

This repository now uses a **single** Vercel Python entrypoint: `api/index.py`.
All routes (including `/api/health`) are served by the main Flask app in `POS sytem.py`.

### Deploy steps
1. Import the repo at https://vercel.com/new.
2. Keep root directory as repository root.
3. Set framework preset to **Other**.
4. Add environment variables:
   - `DATABASE_URL`
   - `SECRET_KEY`
   - `QR_SECRET` (optional)
5. Deploy.

### Verify
- `https://<deployment>/api/health`
- `https://<deployment>/api/products`

### Runtime notes
- WebSockets are not supported by Vercel serverless functions.
- The app exposes HTTP fallback endpoints under `/api/ws/*`.
