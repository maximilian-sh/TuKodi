"""
TuKodi - TU Wien Lecture Stream Kodi Addon
plugin.video.tukodi

Main entry point. Routes plugin:// URLs to the right handler.

URL scheme:
  plugin://plugin.video.tukodi/                          → main menu
  plugin://plugin.video.tukodi/my_courses                → enrolled courses
  plugin://plugin.video.tukodi/course?id=XXX             → course streams
  plugin://plugin.video.tukodi/play?url=...              → play stream
  plugin://plugin.video.tukodi/all_rooms                 → all lecture halls
  plugin://plugin.video.tukodi/play_room?code=...        → play by room code
"""

import sys
import os
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs

# Add lib directory to path
ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
# Translate special:// profile path to real filesystem path
DATA_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
LIB_PATH = os.path.join(ADDON_PATH, 'resources', 'lib')

if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from auth import get_or_create_session, clear_session, login
from tuwel import (
    get_enrolled_courses, get_course_livestreams, get_stream_url_from_page,
    get_all_my_livestreams, room_stream_url, KNOWN_ROOMS, _curl_fetch,
    get_course_opencast, get_opencast_episodes, get_opencast_video_url,
)

HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]


def get_url(**kwargs):
    return '{}?{}'.format(BASE_URL, urllib.parse.urlencode(kwargs))


_CREDS_FILE = os.path.join(DATA_DIR, 'credentials.json')


def _load_credentials_from_file():
    """Fallback: read credentials from a JSON file in the data directory."""
    import json
    if os.path.exists(_CREDS_FILE):
        try:
            with open(_CREDS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_setting(key):
    """Read setting from Kodi settings, with fallback to credentials.json."""
    val = ADDON.getSetting(key)
    if not val:
        creds = _load_credentials_from_file()
        val = creds.get(key, '')
    return val


def get_session():
    """Get authenticated session, using cached cookie if available."""
    username = get_setting('username')
    password = get_setting('password')

    if not username or not password:
        xbmcgui.Dialog().ok(
            'TuKodi',
            'Bitte TUaccount Zugangsdaten in den Addon-Einstellungen eintragen.'
        )
        ADDON.openSettings()
        return None

    os.makedirs(DATA_DIR, exist_ok=True)

    # Return cached session immediately — no dialog, no network round-trip
    from auth import _load_session
    session = _load_session(DATA_DIR)
    if session:
        return session

    # No cached session: need to actually log in — show progress dialog
    dialog = xbmcgui.DialogProgress()
    dialog.create('TuKodi', 'Anmeldung bei TUWEL...')

    try:
        session = get_or_create_session(username, password, DATA_DIR)
        dialog.close()
        return session

    except RuntimeError as e:
        dialog.close()
        msg = str(e)
        if 'Login failed' in msg:
            clear_session(DATA_DIR)
            xbmcgui.Dialog().ok('TuKodi', f'Anmeldung fehlgeschlagen: {msg}\n\nBitte Zugangsdaten prüfen.')
        else:
            xbmcgui.Dialog().ok('TuKodi', f'Fehler: {msg}')
        return None
    except Exception as e:
        dialog.close()
        xbmcgui.Dialog().ok('TuKodi', f'Verbindungsfehler: {e}')
        return None



def menu_main():
    """Show main menu."""
    items = [
        ('Meine Vorlesungen (TUWEL)', get_url(action='my_courses'), False),
        ('Alle Hörsäle (direkt)', get_url(action='all_rooms'), False),
        ('Einstellungen', get_url(action='settings'), False),
    ]

    for label, url, is_folder in items:
        li = xbmcgui.ListItem(label=label)
        li.setProperty('IsPlayable', 'false' if is_folder else 'false')
        xbmcplugin.addDirectoryItem(HANDLE, url, li, True)

    xbmcplugin.endOfDirectory(HANDLE)


def menu_my_courses():
    """Show enrolled courses from TUWEL."""
    session = get_session()
    if not session:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    try:
        courses = get_enrolled_courses(session)

        if not courses:
            xbmcgui.Dialog().ok('TuKodi', 'Keine Kurse gefunden.')
            xbmcplugin.endOfDirectory(HANDLE)
            return

        for course in courses:
            li = xbmcgui.ListItem(label=course['name'])
            url = get_url(action='course_streams', course_url=course['url'], course_name=course['name'])
            xbmcplugin.addDirectoryItem(HANDLE, url, li, True)

        xbmcplugin.endOfDirectory(HANDLE)

    except Exception as e:
        xbmcgui.Dialog().ok('TuKodi', f'Fehler beim Laden der Kurse: {e}')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def menu_course_streams(course_url, course_name):
    """Show livestream activities and opencast recording folders for a course."""
    session = get_session()
    if not session:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    try:
        streams = get_course_livestreams(session, course_url)
        recordings = get_course_opencast(session, course_url)

        if not streams and not recordings:
            xbmcgui.Dialog().ok('TuKodi', f'Keine Streams oder Aufzeichnungen in "{course_name}" gefunden.')
            xbmcplugin.endOfDirectory(HANDLE)
            return

        for stream in streams:
            li = xbmcgui.ListItem(label=stream['name'])
            li.setProperty('IsPlayable', 'true')
            url = get_url(
                action='play_tuwel',
                tuwel_url=stream['url'],
                stream_name=stream['name']
            )
            xbmcplugin.addDirectoryItem(HANDLE, url, li, False)

        for rec in recordings:
            li = xbmcgui.ListItem(label=f'[Aufzeichnungen] {rec["name"]}')
            url = get_url(
                action='opencast_episodes',
                opencast_url=rec['url'],
                opencast_name=rec['name']
            )
            xbmcplugin.addDirectoryItem(HANDLE, url, li, True)

        xbmcplugin.endOfDirectory(HANDLE)

    except Exception as e:
        xbmcgui.Dialog().ok('TuKodi', f'Fehler: {e}')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def menu_opencast_episodes(opencast_url, opencast_name):
    """List episodes from an Opencast series."""
    session = get_session()
    if not session:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    try:
        episodes = get_opencast_episodes(session, opencast_url)

        if not episodes:
            xbmcgui.Dialog().ok('TuKodi', f'Keine Aufzeichnungen in "{opencast_name}" gefunden.')
            xbmcplugin.endOfDirectory(HANDLE)
            return

        for ep in episodes:
            label = ep['name']
            if ep.get('date'):
                label += f'  [{ep["date"]}]'
            if ep.get('duration'):
                label += f'  {ep["duration"]}'
            li = xbmcgui.ListItem(label=label)
            li.setProperty('IsPlayable', 'true')
            if ep.get('thumb'):
                li.setArt({'thumb': ep['thumb'], 'icon': ep['thumb']})
            url = get_url(
                action='play_recording',
                episode_url=ep['url'],
                episode_name=ep['name']
            )
            xbmcplugin.addDirectoryItem(HANDLE, url, li, False)

        xbmcplugin.endOfDirectory(HANDLE)

    except Exception as e:
        xbmcgui.Dialog().ok('TuKodi', f'Fehler: {e}')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def play_opencast_episode(episode_url, episode_name=''):
    """Fetch and play an Opencast recording."""
    session = get_session()
    if not session:
        return

    try:
        video_url = get_opencast_video_url(session, episode_url)

        if not video_url:
            xbmcgui.Dialog().ok('TuKodi', 'Keine Video-URL gefunden.')
            return

        # Play via Kodi's native player (not ISA) — supports x2+ speed.
        # Append headers via URL |notation so the request is authenticated.
        ua = (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        url_with_headers = video_url + '|User-Agent=' + urllib.parse.quote(ua)
        li = xbmcgui.ListItem(label=episode_name, path=url_with_headers)
        li.setContentLookup(False)
        xbmcplugin.setResolvedUrl(HANDLE, True, li)

    except Exception as e:
        xbmcgui.Dialog().ok('TuKodi', f'Fehler beim Laden der Aufzeichnung: {e}')


def play_tuwel_stream(tuwel_url, stream_name=''):
    """Load stream URL from a TUWEL mod/livestream page and play it."""
    session = get_session()
    if not session:
        return

    try:
        m3u8_url = get_stream_url_from_page(session, tuwel_url)

        if not m3u8_url:
            xbmcgui.Dialog().ok(
                'TuKodi',
                'Stream-URL nicht gefunden.\nMöglicherweise ist kein Live-Stream aktiv.'
            )
            return

        _play_m3u8(m3u8_url, stream_name)

    except Exception as e:
        xbmcgui.Dialog().ok('TuKodi', f'Fehler beim Laden des Streams: {e}')


def menu_all_rooms():
    """Show all known lecture halls for direct playback."""
    for room_name, room_code in KNOWN_ROOMS:
        li = xbmcgui.ListItem(label=room_name)
        li.setProperty('IsPlayable', 'true')
        url = get_url(action='play_room', room_code=room_code, room_name=room_name)
        xbmcplugin.addDirectoryItem(HANDLE, url, li, False)

    xbmcplugin.endOfDirectory(HANDLE)


def _resolve_to_chunklist(master_url):
    """Use curl (HTTP/2) to fetch a master playlist and return the chunklist URL."""
    _headers = [
        'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer: https://tuwel.tuwien.ac.at/',
    ]
    manifest = _curl_fetch(master_url, _headers)
    if manifest and '#EXTM3U' in manifest:
        for line in manifest.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                if line.startswith('http'):
                    return line
                base = master_url.rsplit('/', 1)[0] + '/'
                return base + line
    return master_url


def play_room(room_code, room_name=''):
    """Play a lecture hall stream directly by room code."""
    master_url = room_stream_url(room_code)
    chunklist_url = _resolve_to_chunklist(master_url)
    _play_m3u8(chunklist_url, room_name or room_code)


def _play_m3u8(m3u8_url, title=''):
    """Play an HLS stream URL in Kodi."""
    xbmc.log(f'[TuKodi] Playing: {m3u8_url}', xbmc.LOGINFO)

    # Build header strings.
    # - Kodi url|Header=Value notation needs URL-encoded values
    # - inputstream.adaptive.stream_headers needs raw (unencoded) values
    ua = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    referer = 'https://tuwel.tuwien.ac.at/'

    # For stream_headers: raw values (inputstream.adaptive parses them as-is)
    stream_headers = (
        'User-Agent=' + ua +
        '&Referer=' + referer
    )

    # For URL |notation: values must be URL-encoded
    url_headers = (
        'User-Agent=' + urllib.parse.quote(ua) +
        '&Referer=' + urllib.parse.quote(referer)
    )

    # Append to URL so inputstream.adaptive uses them for the manifest request
    url_with_headers = m3u8_url + '|' + url_headers

    li = xbmcgui.ListItem(label=title, path=url_with_headers)
    li.setMimeType('application/x-mpegURL')
    li.setContentLookup(False)

    # ISA auto-hooks m3u8 URLs; setting stream_headers ensures it uses the
    # right headers for chunklist and segment requests too.
    try:
        li.setProperty('inputstream.adaptive.stream_headers', stream_headers)
    except Exception:
        pass

    xbmcplugin.setResolvedUrl(HANDLE, True, li)


def action_settings():
    """Open addon settings."""
    ADDON.openSettings()
    xbmcplugin.endOfDirectory(HANDLE)


def router(params):
    """Route the plugin call based on the 'action' parameter."""
    action = params.get('action', 'main')

    if action == 'main':
        menu_main()
    elif action == 'my_courses':
        menu_my_courses()
    elif action == 'course_streams':
        menu_course_streams(
            params.get('course_url', ''),
            params.get('course_name', '')
        )
    elif action == 'play_tuwel':
        play_tuwel_stream(
            params.get('tuwel_url', ''),
            params.get('stream_name', '')
        )
    elif action == 'opencast_episodes':
        menu_opencast_episodes(
            params.get('opencast_url', ''),
            params.get('opencast_name', '')
        )
    elif action == 'play_recording':
        play_opencast_episode(
            params.get('episode_url', ''),
            params.get('episode_name', '')
        )
    elif action == 'all_rooms':
        menu_all_rooms()
    elif action == 'play_room':
        play_room(
            params.get('room_code', ''),
            params.get('room_name', '')
        )
    elif action == 'settings':
        action_settings()
    else:
        menu_main()


if __name__ == '__main__':
    params = {}
    if len(sys.argv) > 2 and sys.argv[2]:
        query = sys.argv[2].lstrip('?')
        params = dict(urllib.parse.parse_qsl(query))
    router(params)
