import os
import importlib.util
from vercel_wsgi import handle_wsgi_request

# Load the existing Flask app from the repository (handles spaces in filename)
module_path = os.path.join(os.path.dirname(__file__), '..', 'POS sytem.py')
module_path = os.path.normpath(module_path)

spec = importlib.util.spec_from_file_location('pos_module', module_path)
pos_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pos_module)

flask_app = getattr(pos_module, 'app')

def handler(request, response):
    """Vercel serverless entrypoint that forwards requests to the Flask WSGI app."""
    return handle_wsgi_request(flask_app, request, response)
