from datetime import datetime

def handler(request, response):
    """Lightweight health endpoint for Vercel builds and readiness checks."""
    response.status_code = 200
    return response.json({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat()
    })
