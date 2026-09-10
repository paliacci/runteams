# -*- coding: utf-8 -*-
"""Local Supabase email-OTP session manager.

The browser-facing UI never receives an access or refresh token.  The refresh
token is kept in the operating-system credential store and the short-lived
access token only lives in this process.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


SUPABASE_URL = (os.environ.get("RUNTEAMS_SUPABASE_URL") or
                "https://klvxacpbeyqfjmwtuuui.supabase.co").rstrip("/")
# Supabase's anon key is intentionally a public client credential.  A
# service_role key must never be used by or bundled with the desktop app.
SUPABASE_ANON_KEY = os.environ.get("RUNTEAMS_SUPABASE_ANON_KEY") or (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtsdnhhY3BiZXlxZmptd3R1dXVpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU2NjMwMDcsImV4cCI6MjEwMTIzOTAwN30."
    "cd5uyQC3QfgqjVKo4xyNMTqQLvs8Z0Ox_L3yktkUVxI"
)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AuthError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class KeyringTokenStore:
    """Stores only the rotating refresh token in the OS credential store."""

    service = "ai.runteams.desktop.supabase"
    account = "klvxacpbeyqfjmwtuuui:refresh-token"

    @classmethod
    def _macos_security(cls, arguments, input_value=None):
        """Use Apple's signed Keychain client without exposing secrets in argv."""
        try:
            result = subprocess.run(
                ["/usr/bin/security"] + list(arguments),
                input=input_value,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AuthError("无法访问系统钥匙串") from exc
        return result

    @classmethod
    def _macos_security_set(cls, value):
        """Write through a private pseudo-terminal without putting the token in argv."""
        expect_script = (
            'set timeout 8; set secret [gets stdin]; log_user 0; '
            'spawn -noecho /usr/bin/security add-generic-password -U '
            '-s $env(RUNTEAMS_KEYCHAIN_SERVICE) '
            '-a $env(RUNTEAMS_KEYCHAIN_ACCOUNT) -w; '
            'expect -exact "password data for new item:"; '
            'send -- "$secret\\r"; '
            'expect -exact "retype password for new item:"; '
            'send -- "$secret\\r"; expect eof; '
            'set result [wait]; exit [lindex $result 3]'
        )
        environment = dict(os.environ)
        environment.update(RUNTEAMS_KEYCHAIN_SERVICE=cls.service,
                           RUNTEAMS_KEYCHAIN_ACCOUNT=cls.account)
        try:
            return subprocess.run(
                ["/usr/bin/expect", "-c", expect_script],
                input=value + "\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AuthError("无法访问系统钥匙串") from exc

    @staticmethod
    def _keyring():
        try:
            import keyring
            return keyring
        except ImportError as exc:
            raise AuthError("系统安全存储组件不可用，请重新安装或更新 RunTeams") from exc

    def get(self):
        if sys.platform == "darwin":
            result = self._macos_security([
                "find-generic-password", "-s", self.service, "-a", self.account, "-w",
            ])
            if result.returncode == 44:  # errSecItemNotFound
                return ""
            if result.returncode != 0:
                raise AuthError("无法读取系统钥匙串")
            return result.stdout.rstrip("\r\n")
        try:
            return self._keyring().get_password(self.service, self.account) or ""
        except AuthError:
            raise
        except Exception as exc:
            raise AuthError("无法读取系统钥匙串") from exc

    def set(self, value):
        if sys.platform == "darwin":
            value = str(value or "")
            if not value or "\n" in value or "\r" in value:
                raise AuthError("登录服务返回了无效凭证")
            # `security -w` insists on a terminal. `expect` gives it a private
            # pseudo-terminal while the token itself enters only through stdin.
            result = self._macos_security_set(value)
            if result.returncode != 0:
                raise AuthError("无法写入系统钥匙串")
            return
        try:
            self._keyring().set_password(self.service, self.account, value)
        except AuthError:
            raise
        except Exception as exc:
            raise AuthError("无法写入系统钥匙串") from exc

    def delete(self):
        if sys.platform == "darwin":
            result = self._macos_security([
                "delete-generic-password", "-s", self.service, "-a", self.account,
            ])
            if result.returncode not in (0, 44):
                raise AuthError("无法清除系统钥匙串中的登录信息")
            return
        try:
            keyring = self._keyring()
            try:
                keyring.delete_password(self.service, self.account)
            except keyring.errors.PasswordDeleteError:
                pass
        except AuthError:
            raise
        except Exception as exc:
            raise AuthError("无法清除系统钥匙串中的登录信息") from exc


class SupabaseAuthClient:
    def __init__(self, url=SUPABASE_URL, anon_key=SUPABASE_ANON_KEY, timeout=12):
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.timeout = timeout

    def _request(self, path, body, access_token=""):
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apikey": self.anon_key,
        }
        if access_token:
            headers["Authorization"] = "Bearer " + access_token
        request = urllib.request.Request(self.url + path, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                detail = {}
            raise AuthError(detail.get("msg") or detail.get("message") or "认证服务请求失败", exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError, LookupError) as exc:
            raise AuthError("暂时无法连接登录服务，请检查网络后重试") from exc
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthError("登录服务返回了无效响应") from exc

    def request_otp(self, email):
        return self._request("/auth/v1/otp", {"email": email, "create_user": True})

    def verify_otp(self, email, token):
        return self._request("/auth/v1/verify", {"email": email, "token": token, "type": "email"})

    def refresh(self, refresh_token):
        return self._request(
            "/auth/v1/token?grant_type=refresh_token",
            {"refresh_token": refresh_token},
        )

    def logout(self, access_token):
        return self._request("/auth/v1/logout", {}, access_token=access_token)


def _normalized_email(value):
    email = str(value or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise AuthError("请输入有效的邮箱地址", 400)
    return email


def _normalized_otp(value):
    token = re.sub(r"\s+", "", str(value or ""))
    if not re.fullmatch(r"\d{6}", token):
        raise AuthError("请输入邮件中的 6 位验证码", 400)
    return token


class AuthManager:
    def __init__(self, client=None, token_store=None, clock=None,
                 debug_email=None, debug_code=None):
        self.client = client or SupabaseAuthClient()
        self.token_store = token_store or KeyringTokenStore()
        self.clock = clock or time.time
        if debug_email is None and debug_code is None and os.environ.get("RUNTEAMS_ENABLE_DEV_AUTH") == "1":
            debug_email = os.environ.get("RUNTEAMS_DEV_AUTH_EMAIL") or ""
            debug_code = os.environ.get("RUNTEAMS_DEV_AUTH_CODE") or ""
        try:
            self._debug_email = _normalized_email(debug_email) if debug_email else ""
        except AuthError:
            self._debug_email = ""
        self._debug_code = str(debug_code or "") if re.fullmatch(r"\d{6}", str(debug_code or "")) else ""
        if not self._debug_email or not self._debug_code:
            self._debug_email = self._debug_code = ""
        self._lock = threading.RLock()
        self._access_token = ""
        self._expires_at = 0
        self._user = None
        self._debug_user = None

    @staticmethod
    def _public_user(user):
        user = user or {}
        metadata = user.get("user_metadata") or {}
        email = str(user.get("email") or "")
        name = (metadata.get("display_name") or metadata.get("full_name") or
                (email.split("@", 1)[0] if email else "RunTeams 用户"))
        result = {
            "signed_in": True,
            "user_id": str(user.get("id") or ""),
            "email": email,
            "name": str(name),
            "plan": "Debug" if user.get("debug_local") else "Free",
        }
        if user.get("debug_local"):
            result["debug_local"] = True
        return result

    @staticmethod
    def signed_out(error=""):
        result = {
            "signed_in": False,
            "user_id": "",
            "email": "",
            "name": "未登录",
            "plan": "Free",
        }
        if error:
            result["error"] = error
        return result

    def _accept_session(self, payload):
        access_token = str(payload.get("access_token") or "")
        refresh_token = str(payload.get("refresh_token") or "")
        user = payload.get("user") or {}
        if not access_token or not refresh_token or not user.get("id"):
            raise AuthError("登录服务没有返回完整会话")
        # Persist first: the browser is only told that login succeeded after the
        # rotating credential is safely in the OS keychain.
        self.token_store.set(refresh_token)
        try:
            expires_in = max(60, int(payload.get("expires_in") or 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        self._access_token = access_token
        self._expires_at = self.clock() + expires_in
        self._user = user
        return self._public_user(user)

    def request_otp(self, email):
        email = _normalized_email(email)
        if self._debug_email and email == self._debug_email:
            return {"ok": True, "email": email, "debug_local": True}
        try:
            self.client.request_otp(email)
        except AuthError as exc:
            if exc.status == 429:
                raise AuthError("验证码请求过于频繁，请稍后再试", 429) from exc
            raise AuthError("暂时无法发送验证码，请稍后重试", exc.status) from exc
        return {"ok": True, "email": email}

    def verify_otp(self, email, token):
        email, token = _normalized_email(email), _normalized_otp(token)
        with self._lock:
            if self._debug_email and email == self._debug_email:
                if not hmac.compare_digest(token, self._debug_code):
                    raise AuthError("调试验证码无效", 400)
                self._debug_user = {
                    "id": "local-debug-user",
                    "email": email,
                    "user_metadata": {"display_name": "本地调试"},
                    "debug_local": True,
                }
                return self._public_user(self._debug_user)
            try:
                payload = self.client.verify_otp(email, token)
            except AuthError as exc:
                if exc.status in (400, 401, 403):
                    raise AuthError("验证码无效或已过期，请重新获取", 400) from exc
                if exc.status == 429:
                    raise AuthError("验证尝试过于频繁，请稍后再试", 429) from exc
                raise
            return self._accept_session(payload)

    def _refresh(self):
        refresh_token = self.token_store.get()
        if not refresh_token:
            return None
        try:
            payload = self.client.refresh(refresh_token)
        except AuthError as exc:
            if exc.status in (400, 401, 403):
                self.token_store.delete()
                raise AuthError("登录会话已过期，请重新登录", 401) from exc
            raise
        return self._accept_session(payload)

    def session(self):
        with self._lock:
            if self._debug_user:
                return self._public_user(self._debug_user)
            if self._user and self._access_token and self._expires_at > self.clock() + 60:
                return self._public_user(self._user)
            try:
                refreshed = self._refresh()
            except AuthError as exc:
                return self.signed_out(str(exc))
            return refreshed or self.signed_out()

    def access_token(self):
        with self._lock:
            if self._debug_user:
                return ""
            if self._access_token and self._expires_at > self.clock() + 60:
                return self._access_token
            self._refresh()
            return self._access_token

    def logout(self):
        with self._lock:
            if self._debug_user:
                self._debug_user = None
                return {"ok": True}
            remote_error = ""
            if self._access_token:
                try:
                    self.client.logout(self._access_token)
                except AuthError as exc:
                    remote_error = str(exc)
            self._access_token = ""
            self._expires_at = 0
            self._user = None
            self.token_store.delete()
            result = {"ok": True}
            if remote_error:
                result["warning"] = "本机已退出；远端会话将在过期后失效"
            return result


_MANAGER = None
_MANAGER_LOCK = threading.Lock()


def manager():
    global _MANAGER
    if _MANAGER is None:
        with _MANAGER_LOCK:
            if _MANAGER is None:
                _MANAGER = AuthManager()
    return _MANAGER


def request_otp(email):
    return manager().request_otp(email)


def verify_otp(email, token):
    return manager().verify_otp(email, token)


def session():
    return manager().session()


def access_token():
    return manager().access_token()


def logout():
    return manager().logout()
