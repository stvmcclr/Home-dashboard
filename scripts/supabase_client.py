#!/usr/bin/env python3
"""
supabase_client.py — Zero-dependency Supabase REST client
==========================================================
Uses only Python stdlib (urllib). No pip install required.
"""

import json
import os
import urllib.request
import urllib.parse
from typing import Any


def _load_config():
    script_dir  = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    config_path = os.path.join(project_dir, "config.json")
    with open(config_path) as f:
        cfg = json.load(f)
    sb = cfg["supabase"]
    key = sb.get("service_role_key") or sb["anon_key"]
    return sb["url"], key


class SupabaseClient:
    def __init__(self, url: str = None, key: str = None):
        if url and key:
            self.url = url.rstrip("/")
            self.key = key
        else:
            self.url, self.key = _load_config()
            self.url = self.url.rstrip("/")

    def _headers(self, extra: dict = None) -> dict:
        h = {
            "apikey":        self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, body=None, params: dict = None, extra_headers: dict = None):
        url = f"{self.url}/rest/v1/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req  = urllib.request.Request(url, data=data, headers=self._headers(extra_headers), method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                text = resp.read().decode()
                return json.loads(text) if text else []
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            raise RuntimeError(f"Supabase {method} {path} → {e.code}: {err}")

    # ── CRUD helpers ──────────────────────────────────────────────────────────

    def select(self, table: str, query: str = "*", filters: dict = None, order: str = None, limit: int = None):
        """SELECT rows. filters = {'column': 'eq.value'} etc."""
        params = {"select": query}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit:
            params["limit"] = str(limit)
        return self._request("GET", table, params=params)

    def insert(self, table: str, rows: list[dict], upsert: bool = False):
        """INSERT rows (list of dicts). upsert=True uses ON CONFLICT DO UPDATE."""
        extra = {"Prefer": "resolution=merge-duplicates,return=minimal"} if upsert else {"Prefer": "return=minimal"}
        return self._request("POST", table, body=rows, extra_headers=extra)

    def upsert(self, table: str, rows: list[dict]):
        return self.insert(table, rows, upsert=True)

    def update(self, table: str, values: dict, filters: dict):
        params = dict(filters)
        return self._request("PATCH", table, body=values, params=params, extra_headers={"Prefer": "return=minimal"})

    def delete(self, table: str, filters: dict):
        return self._request("DELETE", table, params=filters)

    def count(self, table: str, filters: dict = None) -> int:
        """Return row count for a table."""
        params = {"select": "id"}
        if filters:
            params.update(filters)
        url  = f"{self.url}/rest/v1/{table}?" + urllib.parse.urlencode(params)
        req  = urllib.request.Request(url, headers={**self._headers(), "Prefer": "count=exact", "Range": "0-0"})
        try:
            with urllib.request.urlopen(req) as resp:
                cr = resp.headers.get("content-range", "*/0")
                return int(cr.split("/")[-1]) if "/" in cr else 0
        except urllib.error.HTTPError:
            return 0


# Module-level singleton (lazy)
_client = None

def get_client() -> SupabaseClient:
    global _client
    if _client is None:
        _client = SupabaseClient()
    return _client
