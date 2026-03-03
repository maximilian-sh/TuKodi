"""
TUWEL SAML2 Authentication

Flow:
1. GET tuwel.tuwien.ac.at/auth/saml2/login.php  → redirects to IdP
2. GET idp.zid.tuwien.ac.at/.../loginuserpass    → login form
3. POST username + password + AuthState           → SAMLResponse form
4. POST SAMLResponse back to TUWEL ACS           → MoodleSessiontuwel cookie
"""

import re
import os
import json
import pickle
import urllib.parse
from html.parser import HTMLParser

import requests  # provided via script.module.requests dependency in addon.xml

TUWEL_BASE = 'https://tuwel.tuwien.ac.at'
TUWEL_AUTH_URL = 'https://tuwel.tuwien.ac.at/auth/saml2/login.php'
SESSION_FILE_NAME = 'tukodi_session.pkl'


def _get_session_path(data_dir):
    return os.path.join(data_dir, SESSION_FILE_NAME)


def _save_session(session, data_dir):
    path = _get_session_path(data_dir)
    with open(path, 'wb') as f:
        pickle.dump(session.cookies, f)


def _load_session(data_dir):
    path = _get_session_path(data_dir)
    if not os.path.exists(path):
        return None
    session = requests.Session()
    session.headers.update({'User-Agent': _get_user_agent()})
    with open(path, 'rb') as f:
        session.cookies = pickle.load(f)
    return session


def _get_user_agent():
    return (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )


class FormParser(HTMLParser):
    """Extracts all form fields and action URL from HTML."""

    def __init__(self):
        super().__init__()
        self.forms = []
        self._current_form = None
        self._in_form = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self._current_form = {
                'action': attrs.get('action', ''),
                'method': attrs.get('method', 'post').lower(),
                'fields': {}
            }
            self._in_form = True
        elif tag == 'input' and self._in_form:
            name = attrs.get('name')
            value = attrs.get('value', '')
            if name:
                self._current_form['fields'][name] = value

    def handle_endtag(self, tag):
        if tag == 'form' and self._in_form:
            self.forms.append(self._current_form)
            self._current_form = None
            self._in_form = False


def _parse_forms(html, base_url=''):
    parser = FormParser()
    parser.feed(html)
    forms = []
    for form in parser.forms:
        action = form['action']
        if action and not action.startswith('http'):
            action = urllib.parse.urljoin(base_url, action)
        form['action'] = action
        forms.append(form)
    return forms



def login(username, password, data_dir=None):
    """
    Authenticate against TUWEL via SAML2 SSO.
    Returns a requests.Session with valid cookies, or None on failure.
    """
    session = requests.Session()
    session.headers.update({'User-Agent': _get_user_agent()})

    # Step 1: Start SAML2 flow
    resp = session.get(TUWEL_AUTH_URL, timeout=15)

    # Should now be at IdP login form
    if 'loginuserpass' not in resp.url and 'login' not in resp.url.lower():
        # Maybe already logged in or unexpected redirect
        if TUWEL_BASE in resp.url:
            return session

    login_url = resp.url
    html = resp.text

    # Step 2: Parse the login form
    forms = _parse_forms(html, login_url)
    login_form = None
    for form in forms:
        if 'AuthState' in form['fields'] or 'username' in form['fields'] or 'password' in form['fields']:
            login_form = form
            break

    if not login_form:
        raise RuntimeError('Could not find login form on IdP page')

    # Step 3: Submit credentials
    post_data = dict(login_form['fields'])
    post_data['username'] = username
    post_data['password'] = password

    post_data.setdefault('totp', '')

    form_action = login_form['action'] or login_url
    resp2 = session.post(form_action, data=post_data, timeout=15)

    # Step 4: Check for SAMLResponse (IdP → SP redirect)
    if 'SAMLResponse' in resp2.text:
        forms2 = _parse_forms(resp2.text, resp2.url)
        saml_form = None
        for form in forms2:
            if 'SAMLResponse' in form['fields']:
                saml_form = form
                break

        if saml_form:
            acs_url = saml_form['action']
            saml_data = {
                'SAMLResponse': saml_form['fields']['SAMLResponse'],
                'RelayState': saml_form['fields'].get('RelayState', ''),
            }
            resp3 = session.post(acs_url, data=saml_data, timeout=15)

    # Verify we got a valid Moodle session
    moodle_cookie = session.cookies.get('MoodleSessiontuwel')
    if not moodle_cookie:
        raise RuntimeError('Login failed: no MoodleSessiontuwel cookie received')

    if data_dir:
        _save_session(session, data_dir)

    return session


def get_or_create_session(username, password, data_dir=None):
    """
    Return a cached session if one exists, otherwise login and cache the new one.
    The cached session is trusted without a network round-trip; if it has expired
    the caller will see a redirect/error on the next real request and should call
    clear_session() + get_or_create_session() to re-authenticate.
    """
    if data_dir:
        session = _load_session(data_dir)
        if session:
            return session

    # No cached session — do a fresh login
    return login(username, password, data_dir)


def clear_session(data_dir):
    """Remove cached session."""
    path = _get_session_path(data_dir)
    if os.path.exists(path):
        os.remove(path)
