"""API keys: where they are kept and how they are found.

Keys live in the Windows Credential Manager (the store the OS uses for saved
passwords), written through the Win32 CredWrite/CredRead functions so no
extra package is needed. They never go into a profile file. Keys set as
environment variables (`ANTHROPIC_API_KEY`, `DEEPL_AUTH_KEY`) still work,
including when the variable was set in the user environment after the app
started; the Credential Manager entry wins when both exist.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

DEEPL_KEY = "DEEPL_AUTH_KEY"
ANTHROPIC_KEY = "ANTHROPIC_API_KEY"


class SecretStore(Protocol):
    """Named secrets. `get` returns None when the name is unset."""

    description: str  # where the secrets live, for status text

    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class MemorySecretStore:
    """In-memory store for tests and for running without Credential Manager."""

    description = "memory"

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)


# -- Windows Credential Manager ------------------------------------------------------

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi32.CredReadW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.POINTER(_CREDENTIAL)),
]
_advapi32.CredReadW.restype = wintypes.BOOL
_advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
_advapi32.CredWriteW.restype = wintypes.BOOL
_advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
_advapi32.CredDeleteW.restype = wintypes.BOOL
_advapi32.CredFree.argtypes = [ctypes.c_void_p]
_advapi32.CredFree.restype = None


class WindowsCredentialStore:
    """Generic credentials named '<prefix>/<name>' in the user's vault. The
    secret is stored as UTF-16, the convention PowerShell and keyring use,
    so the entries are readable from those tools as well."""

    description = "Windows Credential Manager"

    def __init__(self, prefix: str = "gametl") -> None:
        self.prefix = prefix

    def _target(self, name: str) -> str:
        return f"{self.prefix}/{name}"

    def get(self, name: str) -> str | None:
        credential = ctypes.POINTER(_CREDENTIAL)()
        if not _advapi32.CredReadW(self._target(name), _CRED_TYPE_GENERIC, 0, ctypes.byref(credential)):
            return None  # not found (or not readable): treated as unset
        try:
            size = credential.contents.CredentialBlobSize
            if not size:
                return None
            blob = ctypes.string_at(credential.contents.CredentialBlob, size)
        finally:
            _advapi32.CredFree(credential)
        return blob.decode("utf-16-le") if size % 2 == 0 else blob.decode("utf-8", errors="replace")

    def set(self, name: str, value: str) -> None:
        blob = value.encode("utf-16-le")
        buffer = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
        credential = _CREDENTIAL()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = self._target(name)
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = self.prefix
        if not _advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def delete(self, name: str) -> None:
        if not _advapi32.CredDeleteW(self._target(name), _CRED_TYPE_GENERIC, 0):
            error = ctypes.get_last_error()
            if error != _ERROR_NOT_FOUND:
                raise ctypes.WinError(error)


# -- lookup ------------------------------------------------------------------------


def user_environment_variable(name: str) -> str | None:
    """The variable from this process, else from the Windows user environment
    (set after the process started), copied into os.environ."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    if value:
        os.environ[name] = str(value)
        return str(value)
    return None


def resolve_key(name: str, secrets: SecretStore | None = None) -> tuple[str, str] | None:
    """(key, where it came from) or None when unset. The Credential Manager
    entry wins over an environment variable."""
    secrets = secrets if secrets is not None else WindowsCredentialStore()
    value = secrets.get(name)
    if value:
        return value, secrets.description
    value = user_environment_variable(name)
    if value:
        return value, "environment variable"
    return None


def key_status(name: str, secrets: SecretStore | None = None) -> str:
    """Short text for the settings window; never includes the key itself."""
    found = resolve_key(name, secrets)
    return f"set ({found[1]})" if found else "not set"


def anthropic_api_key(secrets: SecretStore | None = None) -> str | None:
    found = resolve_key(ANTHROPIC_KEY, secrets)
    return found[0] if found else None


def has_anthropic_credentials(secrets: SecretStore | None = None) -> bool:
    """True when the Anthropic SDK will be able to authenticate: a key from
    the store or the environment, an auth token, or the SDK's own config."""
    if anthropic_api_key(secrets) or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()
