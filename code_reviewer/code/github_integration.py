"""Guarded, read-only GitHub review adapter.

This module deliberately stops at fetching a diff and preparing local proposals.
It never creates comments, pushes commits, or applies patches remotely.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

MAX_DIFF_BYTES = 512 * 1024


def _request_json(url: str, token: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ai-code-reviewer-read-only",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read(MAX_DIFF_BYTES + 1).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub returned an unexpected response.")
    return payload


def fetch_pull_request_diff(owner: str, repository: str, number: int, token: str | None = None) -> dict[str, Any]:
    """Fetch PR metadata and the patch only; no write endpoint is exposed."""
    access_token = token or os.getenv("GITHUB_TOKEN")
    if not access_token:
        return {"status": "unavailable", "error": "GITHUB_TOKEN is not configured.", "files": []}
    if not owner or not repository or int(number) < 1:
        return {"status": "failed", "error": "A valid owner, repository, and PR number are required.", "files": []}

    url = f"https://api.github.com/repos/{owner}/{repository}/pulls/{int(number)}/files"
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "ai-code-reviewer-read-only",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read(MAX_DIFF_BYTES + 1).decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"status": "failed", "error": f"Read-only GitHub request failed: {exc}", "files": []}

    if not isinstance(payload, list):
        return {"status": "failed", "error": "GitHub returned an unexpected file list.", "files": []}
    files = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        patch = item.get("patch") or ""
        files.append(
            {
                "filename": str(item.get("filename", "")),
                "status": str(item.get("status", "")),
                "additions": int(item.get("additions", 0) or 0),
                "deletions": int(item.get("deletions", 0) or 0),
                "patch": patch[:MAX_DIFF_BYTES],
            }
        )
    return {
        "status": "ready",
        "owner": owner,
        "repository": repository,
        "number": int(number),
        "files": files,
        "write_actions": "disabled",
    }


def prepare_local_review(diff_result: dict[str, Any]) -> dict[str, Any]:
    """Mark fetched content as a local proposal requiring user confirmation."""
    if diff_result.get("status") != "ready":
        return diff_result
    return {
        **diff_result,
        "status": "proposal",
        "approval_required": True,
        "write_actions": "disabled",
    }
