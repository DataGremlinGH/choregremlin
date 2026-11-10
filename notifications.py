"""Outbound family notification delivery."""
import json
from urllib import request


def send_webhook(url, title, body='', kind='general', target_url='/'):
    url = (url or '').strip()
    if not url or not url.lower().startswith(('http://', 'https://')):
        return False
    text = title or 'Chore Gremlin'
    if body:
        text = f'{text}\n{body}'
    payload = {
        'title': title or 'Chore Gremlin',
        'body': body or '',
        'text': text,
        'kind': kind or 'general',
        'url': target_url or '/',
        'source': 'Chore Gremlin',
    }
    req = request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'ChoreGremlin/2.0',
        },
        method='POST',
    )
    try:
        with request.urlopen(req, timeout=4) as response:
            return 200 <= response.status < 300
    except Exception:
        return False
