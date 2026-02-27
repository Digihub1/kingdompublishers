# kingdompublishers

## Deploying to Vercel

This project is configured to run as Python Serverless Functions on Vercel.

### 1) Import repository
- Go to **Vercel → Add New Project**.
- Import this GitHub repository.
- Keep the **Root Directory** as the repository root.
- Framework preset: **Other**.

### 2) Environment variables
Set these in **Project Settings → Environment Variables**:
- `DATABASE_URL`
- `SECRET_KEY`
- `QR_SECRET` (optional)

### 3) Deploy
- Trigger deploy (automatic after import).
- Verify endpoints:
  - `/api/health`
  - `/api/products`

### 4) Notes
- WebSockets are not supported on Vercel serverless functions.
- HTTP fallback endpoints are available under `/api/ws/*`.
