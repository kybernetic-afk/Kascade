"""At-rest encryption for secrets, backed by the Windows Data Protection API.

DPAPI (CryptProtectData / CryptUnprotectData) encrypts data so that only the
current Windows user account on this machine can decrypt it - no key to manage,
and a config file copied elsewhere can't be read. Accessed via ctypes so there
is no extra runtime dependency.

`protect`/`unprotect` deal in base64 strings. On a non-Windows host (dev only -
the app ships Windows-only) DPAPI is unavailable and `protect` raises, leaving
callers to fall back to storing the value as-is.
"""
import base64
import ctypes
import sys
from ctypes import wintypes

_IS_WIN = sys.platform == "win32"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


if _IS_WIN:
    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _run(func, data: bytes) -> bytes:
    blob_in, _keepalive = _blob(data)
    blob_out = _Blob()
    if not func(ctypes.byref(blob_in), None, None, None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
        raise OSError(f"DPAPI call failed (error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(blob_out.pbData)


def available() -> bool:
    return _IS_WIN


def protect(text: str) -> str:
    """Encrypt `text` for the current user; returns a base64 string."""
    if not _IS_WIN:
        raise OSError("DPAPI is only available on Windows")
    return base64.b64encode(_run(_crypt32.CryptProtectData, text.encode("utf-8"))).decode("ascii")


def unprotect(token: str) -> str:
    """Decrypt a base64 string produced by `protect`. Raises if not decryptable."""
    if not _IS_WIN:
        raise OSError("DPAPI is only available on Windows")
    raw = base64.b64decode(token.encode("ascii"))
    return _run(_crypt32.CryptUnprotectData, raw).decode("utf-8")
