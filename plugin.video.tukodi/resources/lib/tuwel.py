"""
TUWEL / LectureTube interaction.

Handles:
- Listing enrolled courses
- Finding active livestream activities
- Extracting stream URLs from mod/livestream pages
- Listing and playing Opencast recordings (mod/opencast)
"""

import re
import subprocess
import urllib.parse

TUWEL_BASE = 'https://tuwel.tuwien.ac.at'
LECTURETUBE_LIVE_BASE = 'https://live.video.tuwien.ac.at/lecturetube-live'

# Known lecture halls with their room codes
# Used as fallback / direct browsing mode
KNOWN_ROOMS = [
    ('GM 1 Audi-Max', 'bau178a-gm-1-audi-max'),
    ('GM 2 Radinger', 'bd01b33-gm-2-radinger-hoersaal'),
    ('GM 3 Vortmann', 'ba02a05-gm-3-vortmann-hoersaal'),
    ('GM 4 Knoller', 'bd02d32-gm-4-knoller-hoersaal'),
    ('GM 5 Praktikum', 'bau276a-gm-5-praktikum-hs'),
    ('HS 7 Schuette-Lihotzky', 'aheg07-hs-7-schuette-lihotzky-bi'),
    ('HS 8 Heinz-Parkus', 'ae0141-hs-8-heinz-parkus'),
    ('HS 13 Ernst-Melan', 'ae0239-hs-13-ernst-melan'),
    ('HS 17 Friedrich-Hartmann', 'ae0341-hs-17-friedrich-hartmann'),
    ('HS 18 Czuber', 'ae0238-hs-18-czuber'),
    ('Hoersaal 6', 'aeeg40-hoersaal-6'),
    ('EI 7', 'cdeg13-ei-7-hoersaal'),
    ('EI 8 Poetzl', 'cdeg08-ei-8-poetzl-hs'),
    ('EI 9 Hlawka', 'caeg17-ei-9-hlawka-hs'),
    ('EI 10 Fritz-Paschke', 'caeg31-ei-10-fritz-paschke-hs'),
    ('Informatikhoersaal', 'deu116-informatikhoersaal'),
    ('FAV Hoersaal-1', 'heeg02-fav-hoersaal-1'),
    ('Seminarraum FAV 01A', 'he0102-seminarraum-fav-01-a'),
    ('FH Hoersaal-1', 'dc02h03-fh-hoersaal-1'),
    ('FH Hoersaal-5', 'da02g15-fh-hoersaal-5'),
    ('FH Hoersaal-6', 'da02k01-fh-hoersaal-6'),
    ('FH 8 Noebauer', 'db02h12-fh-8-noebauer-hs'),
    ('HS Atrium-1', 'ozeg80-hs-atrium-1'),
    ('HS Atrium-2', 'ozeg76-hs-atrium-2'),
    ('Sem-R DA-gruen-02-A', 'da02e08-sem-r-da-gruen-02-a'),
    ('Sem-R DA-gruen-02-C', 'da02f20-sem-r-da-gruen-02-c'),
    ('Seminarraum BA 02A', 'ba02g02-seminarraum-ba-02a'),
    ('Seminarraum BA 02B', 'ba02a17-seminarraum-ba-02b'),
]


def room_stream_url(room_code):
    """Build the HLS stream URL for a known room code."""
    return f'{LECTURETUBE_LIVE_BASE}/{room_code}/playlist.m3u8'


def get_enrolled_courses(session):
    """
    Fetch enrolled courses from the TUWEL dashboard.
    Returns list of dicts: {id, shortname, fullname, url}
    """
    resp = session.get(TUWEL_BASE + '/my/courses.php', timeout=15)
    html = resp.text
    courses = []

    # Find course links in the page
    # Pattern: /course/view.php?id=XXXX
    matches = re.findall(
        r'href="(https://tuwel\.tuwien\.ac\.at/course/view\.php\?id=(\d+))"[^>]*>'
        r'(.*?)</a>',
        html, re.DOTALL
    )
    seen = set()
    for url, course_id, name in matches:
        if course_id in seen:
            continue
        seen.add(course_id)
        # Clean up name
        name = re.sub(r'<[^>]+>', '', name).strip()
        name = re.sub(r'\s+', ' ', name)
        if name:
            courses.append({
                'id': course_id,
                'name': name,
                'url': url,
            })

    return courses


def get_course_livestreams(session, course_url):
    """
    Fetch a course page and find all mod/livestream activity links.
    Returns list of dicts: {id, name, url}
    """
    resp = session.get(course_url, timeout=15)
    html = resp.text
    streams = []
    seen = set()

    # Find mod/livestream links
    matches = re.findall(
        r'href="(https://tuwel\.tuwien\.ac\.at/mod/livestream/view\.php\?id=(\d+))"[^>]*>'
        r'(.*?)</a>',
        html, re.DOTALL
    )
    for url, activity_id, name in matches:
        if activity_id in seen:
            continue
        seen.add(activity_id)
        name = re.sub(r'<[^>]+>', '', name).strip()
        name = re.sub(r'\s+', ' ', name)
        if not name:
            name = f'Livestream {activity_id}'
        streams.append({
            'id': activity_id,
            'name': name,
            'url': url,
        })

    return streams


def _curl_fetch(url, headers=None):
    """
    Fetch a URL using the system curl binary (supports HTTP/2).
    Returns response body as string, or None on error.
    """
    cmd = ['curl', '-sL', '--max-time', '15']
    for h in (headers or []):
        cmd += ['-H', h]
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=20)
        return result.stdout.decode('utf-8', errors='replace')
    except Exception:
        return None


def get_stream_url_from_page(session, livestream_url):
    """
    Load a mod/livestream page, extract the master playlist URL, then use
    curl (HTTP/2) to resolve the CDN redirect and parse the chunklist URL.
    Returning the chunklist URL directly avoids inputstream.adaptive having
    to follow the redirect chain itself.
    Returns the chunklist m3u8 URL string, or None if not found.
    """
    resp = session.get(livestream_url, timeout=15)
    html = resp.text

    # Find the master playlist URL in the page
    master_url = None
    match = re.search(
        r'<source\s+src=["\']([^"\']+\.m3u8[^"\']*)["\']',
        html
    )
    if match:
        master_url = match.group(1)
    else:
        match2 = re.search(
            r'["\']([^"\']*live(?:\.|-cdn-\d+\.)?video\.tuwien\.ac\.at[^"\']*\.m3u8[^"\']*)["\']',
            html
        )
        if match2:
            master_url = match2.group(1)

    if not master_url:
        return None

    # Use curl to fetch the master playlist (follows CDN redirect via HTTP/2)
    _headers = [
        'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer: https://tuwel.tuwien.ac.at/',
    ]
    manifest = _curl_fetch(master_url, _headers)
    if not manifest or '#EXTM3U' not in manifest:
        # curl failed; return master URL and let Kodi try
        return master_url

    # Extract the chunklist (variant stream) URL from the master playlist
    chunklist_url = None
    for line in manifest.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            # Resolve relative URLs against the master playlist base
            if line.startswith('http'):
                chunklist_url = line
            else:
                base = master_url.rsplit('/', 1)[0] + '/'
                chunklist_url = base + line
            break

    return chunklist_url or master_url


def get_course_opencast(session, course_url):
    """
    Fetch a course page and find all mod/opencast activity links.
    Returns list of dicts: {id, name, url}
    """
    resp = session.get(course_url, timeout=15)
    html = resp.text
    activities = []
    seen = set()

    matches = re.findall(
        r'href="(https://tuwel\.tuwien\.ac\.at/mod/opencast/view\.php\?id=(\d+))"[^>]*>'
        r'(.*?)</a>',
        html, re.DOTALL
    )
    for url, activity_id, name in matches:
        if activity_id in seen:
            continue
        seen.add(activity_id)
        name = re.sub(r'<[^>]+>', '', name).strip()
        name = re.sub(r'\s+', ' ', name)
        if not name:
            name = f'Aufzeichnungen {activity_id}'
        activities.append({'id': activity_id, 'name': name, 'url': url})

    return activities


def get_opencast_episodes(session, opencast_url):
    """
    Fetch the Opencast series list page and return all episodes.
    Returns list of dicts: {id, name, date, duration, url}
    """
    resp = session.get(opencast_url, timeout=15)
    html = resp.text
    episodes = []
    seen = set()

    # Each row: <a href="...?id=X&e=UUID">Title</a>  date  duration
    matches = re.findall(
        r'href="(https://tuwel\.tuwien\.ac\.at/mod/opencast/view\.php\?[^"]*&amp;e=([^"&]+))"[^>]*>'
        r'(.*?)</a>'
        r'.*?<td[^>]*>([^<]*)</td>'   # duration
        r'.*?<td[^>]*>([^<]*)</td>',  # date
        html, re.DOTALL
    )
    for url, ep_id, name, duration, date in matches:
        if ep_id in seen:
            continue
        seen.add(ep_id)
        name = re.sub(r'<[^>]+>', '', name).strip()
        name = re.sub(r'\s+', ' ', name)
        url = url.replace('&amp;', '&')
        duration = duration.strip()
        date = date.strip()
        if name:
            episodes.append({
                'id': ep_id,
                'name': name,
                'date': date,
                'duration': duration,
                'url': url,
            })

    return episodes


def get_opencast_video_url(session, episode_url):
    """
    Fetch an Opencast episode page and extract the best video URL.
    Prefers the 'presenter' (camera) stream, then 'presentation' (slides).
    Returns the HLS m3u8 URL (master=true) if available, else 1080p MP4.
    Returns None if no video found.
    """
    import json as _json
    resp = session.get(episode_url, timeout=15)
    html = resp.text

    # The page embeds a JSON block with "streams":[...]
    m = re.search(r'"streams"\s*:\s*(\[.+?\])\s*,\s*"(?:metadata|frameList)"', html, re.DOTALL)
    if not m:
        return None

    try:
        streams = _json.loads(m.group(1))
    except Exception:
        return None

    # Prefer presenter (camera), then presentation (slides)
    def _best_url(stream):
        sources = stream.get('sources', {})
        # Prefer HLS master
        for hls in sources.get('hls', []):
            if hls.get('master'):
                return hls['src']
        # Fallback: highest-res MP4
        best = None
        best_px = 0
        for mp4 in sources.get('mp4', []):
            res = mp4.get('res', {})
            px = res.get('w', 0) * res.get('h', 0)
            if px > best_px:
                best_px = px
                best = mp4['src']
        return best

    for content_pref in ('presenter', 'presentation'):
        for stream in streams:
            if stream.get('content') == content_pref:
                url = _best_url(stream)
                if url:
                    return url

    # Last resort: first stream with any URL
    for stream in streams:
        url = _best_url(stream)
        if url:
            return url

    return None


def get_all_my_livestreams(session):
    """
    Convenience: get all livestream activities across all enrolled courses.
    Returns list of dicts: {course_name, stream_name, stream_id, stream_url, m3u8_url}
    """
    courses = get_enrolled_courses(session)
    results = []

    for course in courses:
        streams = get_course_livestreams(session, course['url'])
        for stream in streams:
            results.append({
                'course_name': course['name'],
                'stream_name': stream['name'],
                'stream_id': stream['id'],
                'tuwel_url': stream['url'],
            })

    return results
