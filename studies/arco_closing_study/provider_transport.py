"""Official HTTPS transport; existing project bindings or environment credentials."""
import datetime as dt
import importlib.util
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

MODELS={'deepseek':'deepseek-v4-pro','luna':'gpt-5.6-luna'}
def utc(): return dt.datetime.now(dt.timezone.utc).isoformat()
def credentials(provider):
    name='DEEPSEEK_API_KEY' if provider=='deepseek' else 'OPENAI_API_KEY'
    key=os.environ.get(name); base='https://api.deepseek.com' if provider=='deepseek' else 'https://api.openai.com/v1'
    if not key: raise RuntimeError('Set '+name+' in your local environment')
    parsed=urlsplit(base)
    if parsed.scheme!='https' or parsed.hostname!=('api.deepseek.com' if provider=='deepseek' else 'api.openai.com') or parsed.username or parsed.password or parsed.query or parsed.fragment: raise RuntimeError('official endpoint required')
    return key,base
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
def request(method,url,key,body=None,timeout=60):
    req=urllib.request.Request(url,data=body,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'application/json'},method=method)
    meta={'method':method,'url':url,'started_utc':utc()}; start=time.perf_counter(); raw=None
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=timeout) as response:
            meta.update(http_status=response.status,x_request_id=response.headers.get('x-request-id')); raw=response.read()
    except urllib.error.HTTPError as exc: meta.update(http_status=exc.code,error_type='HTTPError'); raw=exc.read()
    except Exception as exc: meta.update(http_status=meta.get('http_status'),error_type=type(exc).__name__,error_message=str(exc).replace(key,'[REDACTED]'))
    meta.update(ended_utc=utc(),elapsed_seconds=time.perf_counter()-start)
    if raw is not None and key.encode() in raw: raise RuntimeError('credential in provider body')
    return meta,raw
