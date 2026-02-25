import os
import importlib.util
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Response as WSGIResponse

# Load the existing Flask app from the repository (handles spaces in filename)
module_path = os.path.join(os.path.dirname(__file__), '..', 'POS sytem.py')
module_path = os.path.normpath(module_path)

spec = importlib.util.spec_from_file_location('pos_module', module_path)
pos_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pos_module)

flask_app = getattr(pos_module, 'app')

def handler(request, response):
    """Manual WSGI adapter: convert the incoming Vercel request to a WSGI environ,
    dispatch to the Flask app, and return a Werkzeug Response.
    """
    try:
        method = getattr(request, 'method', 'GET')
        # headers is a mapping-like object
        headers = dict(getattr(request, 'headers', {}) or {})
        path = getattr(request, 'path', None) or getattr(request, 'url', '/')
        query_string = getattr(request, 'query_string', '') or ''

        # request body - try common attribute names
        body = b''
        if hasattr(request, 'get_data'):
            try:
                body = request.get_data()
            except Exception:
                body = getattr(request, 'body', b'') or b''
        else:
            body = getattr(request, 'body', b'') or b''

        builder = EnvironBuilder(path=path, method=method, headers=headers, data=body, query_string=query_string)
        env = builder.get_environ()

        status_headers = {}
        def start_response(status, response_headers, exc_info=None):
            status_headers['status'] = status
            status_headers['headers'] = response_headers

        rv = flask_app.wsgi_app(env, start_response)
        body_bytes = b''.join(rv)
        status = status_headers.get('status', '200 OK')
        status_code = int(status.split()[0])
        resp_headers = dict(status_headers.get('headers', []))

        wresp = WSGIResponse(response=body_bytes, status=status_code, headers=resp_headers)
        return wresp
    except Exception as e:
        err_resp = WSGIResponse(response=(f'Internal server error: {e}').encode(), status=500)
        return err_resp
