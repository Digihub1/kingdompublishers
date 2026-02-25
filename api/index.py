import os
import importlib.util
import asyncio
import inspect
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
        try:
            headers = dict(request.headers or {})
        except Exception:
            headers = dict(getattr(request, 'headers', {}) or {})

        # Path and query handling for different request shapes
        path = '/'
        query_string = ''
        try:
            # Common for Starlette/ASGI Request
            if hasattr(request, 'url') and getattr(request, 'url') is not None:
                url = request.url
                # url may be a URL object
                path = getattr(url, 'path', str(url))
            elif hasattr(request, 'path') and request.path:
                path = request.path
            elif hasattr(request, 'scope') and isinstance(request.scope, dict):
                path = request.scope.get('path', '/')

            # query string
            if hasattr(request, 'query_string') and request.query_string:
                qs = request.query_string
                query_string = qs.decode() if isinstance(qs, (bytes, bytearray)) else str(qs)
            elif hasattr(request, 'query_params') and request.query_params:
                query_string = str(request.query_params)
            elif hasattr(request, 'scope') and isinstance(request.scope, dict):
                qs = request.scope.get('query_string', b'')
                query_string = qs.decode() if isinstance(qs, (bytes, bytearray)) else str(qs)
        except Exception:
            path = getattr(request, 'path', '/') or '/'

        # Body handling (support sync and async request objects)
        body = b''
        try:
            if hasattr(request, 'get_data'):
                body = request.get_data() or b''
            elif hasattr(request, 'body'):
                candidate = request.body
                if callable(candidate):
                    maybe = candidate()
                    if inspect.isawaitable(maybe):
                        try:
                            body = asyncio.get_event_loop().run_until_complete(maybe)
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            body = loop.run_until_complete(maybe)
                            loop.close()
                    else:
                        body = maybe or b''
                else:
                    body = candidate or b''
            else:
                body = getattr(request, 'data', b'') or b''
        except Exception:
            body = b''

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
