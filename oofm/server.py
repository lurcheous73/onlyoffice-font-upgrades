from __future__ import annotations
import base64, hmac, json, re, urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from .config import APP_VERSION, BASE_PATH, BIND_HOST, CONFIG, MAX_UPLOAD, PORT, csrf_value, fetch_bytes, session_value
from .engines import apply_selection, status_data
from .fonts import catalog, install_local_upload, preview_url
from .ui import app_html, login_html

class Handler(BaseHTTPRequestHandler):
    server_version="OOFontManager/"+APP_VERSION
    def log_message(self,fmt:str,*args:Any)->None: print("%s - %s"%(self.address_string(),fmt%args))
    def proxy_ok(self)->bool:
        expected=str(CONFIG.get("proxy_secret","")); return bool(expected) and hmac.compare_digest(self.headers.get("X-OO-Font-Proxy",""),expected)
    def authed(self)->bool:
        c=SimpleCookie(self.headers.get("Cookie","")); got=c.get("oo_font_session"); return bool(got and hmac.compare_digest(got.value,session_value()))
    def csrf_ok(self)->bool: return hmac.compare_digest(self.headers.get("X-CSRF-Token",""),csrf_value())
    def raw_path(self)->str: return self.requestline.split(" ",2)[1]
    def path_only(self)->str: return urllib.parse.urlparse(self.raw_path()).path
    def send_bytes(self,data:bytes,content_type:str,status:int=200,headers:dict[str,str]|None=None)->None:
        self.send_response(status); self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(data))); self.send_header("Cache-Control","no-store" if content_type.startswith("application/json") else "private, max-age=300"); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("X-Frame-Options","SAMEORIGIN"); self.send_header("Content-Security-Policy","default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'self'")
        if headers:
            for k,v in headers.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(data)
    def send_json(self,obj:Any,status:int=200)->None: self.send_bytes(json.dumps(obj,ensure_ascii=False).encode(),"application/json; charset=utf-8",status)
    def read_body(self)->bytes:
        n=int(self.headers.get("Content-Length","0") or 0)
        if n>MAX_UPLOAD*2: raise ValueError("Request too large")
        return self.rfile.read(n)
    def require_proxy(self)->bool:
        if self.proxy_ok(): return True
        self.send_json({"error":"Font Manager must be opened through the ONLYOFFICE portal proxy."},403); return False
    def do_GET(self)->None:
        if not self.require_proxy(): return
        path=self.path_only()
        if path==BASE_PATH:
            self.send_response(302); self.send_header("Location",BASE_PATH+"/"); self.end_headers(); return
        if path==BASE_PATH+"/":
            self.send_bytes((app_html() if self.authed() else login_html()).encode(),"text/html; charset=utf-8"); return
        if path.startswith(BASE_PATH+"/api/") and not self.authed(): self.send_json({"error":"Not signed in"},401); return
        try:
            if path==BASE_PATH+"/api/catalog": self.send_json(catalog()); return
            if path==BASE_PATH+"/api/status": self.send_json(status_data()); return
            m=re.fullmatch(re.escape(BASE_PATH)+r"/api/preview/([a-z0-9-]+)\.woff2",path)
            if m: self.send_bytes(fetch_bytes(preview_url(m.group(1)),60),"font/woff2"); return
            self.send_json({"error":"Not found"},404)
        except Exception as e: self.send_json({"error":str(e)},500)
    def do_POST(self)->None:
        if not self.require_proxy(): return
        path=self.path_only()
        try:
            if path==BASE_PATH+"/login":
                data=urllib.parse.parse_qs(self.read_body().decode("utf-8","replace")); pw=(data.get("password") or [""])[0]
                if hmac.compare_digest(pw,str(CONFIG.get("admin_password",""))):
                    secure="; Secure" if self.headers.get("X-Forwarded-Proto","https")=="https" else ""; self.send_response(303); self.send_header("Location",BASE_PATH+"/"); self.send_header("Set-Cookie",f"oo_font_session={session_value()}; Path={BASE_PATH}/; HttpOnly; SameSite=Strict{secure}"); self.end_headers()
                else: self.send_bytes(login_html("Wrong password").encode(),"text/html; charset=utf-8",401)
                return
            if not self.authed(): self.send_json({"error":"Not signed in"},401); return
            if not self.csrf_ok(): self.send_json({"error":"CSRF check failed"},403); return
            body=json.loads(self.read_body().decode("utf-8"))
            if path==BASE_PATH+"/api/apply":
                ids=body.get("fonts") or []
                if not isinstance(ids,list) or len(ids)>500: raise ValueError("Invalid font selection")
                self.send_json(apply_selection([str(x) for x in ids],bool(body.get("emoji",True)),bool(body.get("fullPacks",True)))); return
            if path==BASE_PATH+"/api/upload":
                raw=base64.b64decode(body.get("data") or "",validate=True); font=install_local_upload(str(body.get("name") or ""),raw,str(body.get("license") or "")); self.send_json({"ok":True,"font":font}); return
            self.send_json({"error":"Not found"},404)
        except Exception as e: self.send_json({"error":str(e)},500)

def main()->None:
    print(f"ONLYOFFICE Font Manager {APP_VERSION} listening on {BIND_HOST}:{PORT}{BASE_PATH}/")
    ThreadingHTTPServer((BIND_HOST,PORT),Handler).serve_forever()
