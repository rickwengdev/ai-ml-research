"""JSON over HTTP to the steering server (server.py), for the scripts that drive it: sweep.py and experiments/*.

Plain urllib, so the scripts need nothing beyond the server's own environment.
"""
import json
import urllib.request


def post(url, body, timeout=600):
    """POST `body` as JSON, return the decoded reply. Generation can take minutes; the default allows ten."""
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as res:
        return json.load(res)
