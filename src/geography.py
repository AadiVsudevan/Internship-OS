"""Conservative discovery scope; location signals are not eligibility verification."""
from __future__ import annotations
import re
from urllib.parse import urlsplit


def in_scope(record: dict, profile: dict) -> bool:
    """Require an India location signal, or an explicitly configured India source.

    A generic remote role or an invitation to Indian applicants abroad does not
    establish that the opportunity takes place in India.
    """
    settings = profile.get('geography', {})
    if settings.get('include_global', True):
        return True
    url = record.get('Source URL', record.get('url', ''))
    host = (urlsplit(url).hostname or '').lower()
    if host in settings.get('india_source_hosts', []):
        return True
    title = record.get('Title', record.get('title', ''))
    text = record.get('Source excerpt', record.get('raw_text', ''))
    if host in settings.get('india_remote_hosts', []) and re.search(
            r'location\s*:\s*work from home\b', text, re.I) and re.search(r'₹|\bINR\b', text):
        return True
    places = settings.get('location_terms', ['India'])
    terms = '|'.join(re.escape(p) for p in places)
    if not terms:
        return False
    cities = [p for p in places if p.lower() != 'india']
    if cities and re.search(r'\b(?:' + '|'.join(re.escape(p) for p in cities) + r')\b', title, re.I):
        return True
    # Avoid treating Indian nationality as evidence of an Indian work location.
    pattern = rf'\b(?:in|at|based in|location\s*[:\-]|locations\s*[:\-])\s*(?:{terms})\b'
    if re.search(pattern, title, re.I):
        return True
    if re.search(rf'\b(?:location|based in|work location)\s*[:\-]?\s*(?:{terms})\b', text, re.I):
        return True
    return bool(re.search(rf'\b(?:{terms})\s*[-:|]\s*(?:internship|fellowship|scholarship|volunteer)', title, re.I))
