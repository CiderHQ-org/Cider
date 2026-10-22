#!/usr/bin/env python3
"""Cache public macOS Roblox deployments for clients whose CDN returns 403.

Only the two documented path shapes below are accepted. No caller-selected
upstream, credentials, cookies, join tickets, or account requests are relayed.
"""
import argparse
import http.server
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

VERSION_PATH = re.compile(r'/v2/client-version/MacPlayer(?:/channel/[A-Za-z0-9_-]{1,64})?')
ARCHIVE_PATH = re.compile(r'/mac/(version-[0-9a-fA-F]{16,64})-RobloxPlayer\.zip')
MAX_ARCHIVE = 512 << 20
MAX_CACHE = 2 << 30


def upstream(url, timeout):
    urls = [url]
    parsed = urllib.parse.urlsplit(url)
    if parsed.netloc == 'setup.rbxcdn.com' and ARCHIVE_PATH.fullmatch(parsed.path):
        urls.extend('https://' + host + parsed.path for host in ('setup-aws.rbxcdn.com', 'setup-ak.rbxcdn.com'))
    for index, candidate in enumerate(urls):
        try:
            response = urllib.request.urlopen(urllib.request.Request(candidate, headers={'User-Agent': 'Quadra-download-mirror/1'}), timeout=timeout)
            break
        except urllib.error.HTTPError as error:
            if error.code != 403 or index == len(urls) - 1:
                raise
            error.close()
        except (urllib.error.URLError, TimeoutError):
            if index == 0 or index == len(urls) - 1:
                raise
    redirected = urllib.parse.urlsplit(response.url)
    if (redirected.scheme != 'https' or redirected.hostname not in
            ('clientsettingscdn.roblox.com', 'clientsettings.roblox.com', 'setup.rbxcdn.com',
             'setup-aws.rbxcdn.com', 'setup-ak.rbxcdn.com')):
        response.close()
        raise ValueError('Unexpected upstream redirect')
    return response


class Cache:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.metadata = {}
        self.metadata_lock = threading.Lock()
        self.archive_locks = [threading.Lock() for _ in range(32)]
        self.downloads = threading.BoundedSemaphore(2)
        self.prune_lock = threading.Lock()

    def version(self, path):
        with self.metadata_lock:
            cached = self.metadata.get(path)
            if cached and time.monotonic() - cached[0] < 60:
                return cached[1]
            for index, host in enumerate(('clientsettingscdn.roblox.com', 'clientsettings.roblox.com')):
                try:
                    with upstream('https://' + host + path, 15) as response:
                        data = json.loads(response.read(65537))
                    if (not isinstance(data, dict)
                            or not isinstance(data.get('version'), str)
                            or not re.fullmatch(r'\d{1,10}(?:\.\d{1,10}){3}', data['version'])
                            or not isinstance(data.get('clientVersionUpload'), str)
                            or not re.fullmatch(r'version-[0-9a-fA-F]{16,64}', data['clientVersionUpload'])):
                        raise ValueError('Invalid upstream deployment metadata')
                    body = json.dumps(data, separators=(',', ':')).encode()
                    if len(self.metadata) >= 64:
                        self.metadata.pop(next(iter(self.metadata)))
                    self.metadata[path] = (time.monotonic(), body)
                    return body
                except (OSError, ValueError):
                    if index:
                        raise

    def archive(self, upload):
        target = self.directory / (upload + '-RobloxPlayer.zip')
        with self.archive_locks[hash(upload) % len(self.archive_locks)]:
            if not target.is_file():
                if not self.downloads.acquire(timeout=5):
                    raise TimeoutError('Download capacity is busy')
                try:
                    self._fetch(upload, target)
                finally:
                    self.downloads.release()
            # Open before pruning can unlink this entry on another thread.
            file = target.open('rb')
            try:
                os.utime(target, None)
            except FileNotFoundError:
                pass
            return file

    def _fetch(self, upload, target):
        temporary = None
        try:
            with upstream(f'https://setup.rbxcdn.com/mac/{upload}-RobloxPlayer.zip', 60) as response:
                expected = int(response.headers.get('Content-Length') or 0)
                if expected < 0 or expected > MAX_ARCHIVE:
                    raise ValueError('Upstream archive exceeds the size limit')
                with tempfile.NamedTemporaryFile(dir=self.directory, prefix='.download-', suffix='.part', delete=False) as output:
                    temporary = Path(output.name)
                    size = 0
                    while chunk := response.read(1 << 20):
                        size += len(chunk)
                        if size > MAX_ARCHIVE:
                            raise ValueError('Upstream archive exceeds the size limit')
                        output.write(chunk)
                if not size or (expected and size != expected):
                    raise ValueError('Incomplete upstream archive')
            if not zipfile.is_zipfile(temporary):
                raise ValueError('Upstream did not return a ZIP archive')
            # ZIP integrity and the embedded version are also checked by the
            # launcher before its installed client is swapped.
            temporary.replace(target)
            self._prune(target)
            logging.info('Cached %s (%d bytes)', upload, size)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _prune(self, keep):
        with self.prune_lock:
            entries = []
            for path in self.directory.glob('version-*-RobloxPlayer.zip'):
                try:
                    info = path.stat()
                    entries.append((info.st_mtime, path, info.st_size))
                except FileNotFoundError:
                    pass
            total = sum(entry[2] for entry in entries)
            for _, path, size in sorted(entries):
                if total <= MAX_CACHE:
                    break
                if path != keep:
                    path.unlink(missing_ok=True)
                    total -= size


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, cache):
        self.cache = cache
        self.capacity = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.capacity.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.capacity.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.capacity.release()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'QuadraDownloads/1'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *_):
        pass  # Do not store client addresses, headers or arbitrary request paths.

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            if self.path == '/healthz':
                self._body(b'{"service":"quadra-roblox-mirror","status":"ok"}', 'application/json', 'no-store')
            elif VERSION_PATH.fullmatch(self.path):
                self._body(self.server.cache.version(self.path), 'application/json', 'public, max-age=60')
            elif match := ARCHIVE_PATH.fullmatch(self.path):
                with self.server.cache.archive(match[1]) as file:
                    self._headers(os.fstat(file.fileno()).st_size, 'application/zip', 'public, max-age=31536000, immutable')
                    if self.command != 'HEAD':
                        shutil.copyfileobj(file, self.wfile, 1 << 20)
            else:
                self.send_error(404, 'Unknown public deployment path')
        except urllib.error.HTTPError as error:
            status = error.code if error.code in (401, 403, 404, 429) else 502
            error.close()
            self.send_error(status, 'Roblox deployment unavailable')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except TimeoutError:
            self.send_error(503, 'Download temporarily busy')
        except (OSError, ValueError):
            logging.warning('Could not fetch public Roblox deployment', exc_info=True)
            self.send_error(502, 'Could not fetch a complete Roblox deployment')

    def _headers(self, size, content_type, cache_control):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(size))
        self.send_header('Cache-Control', cache_control)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()

    def _body(self, data, content_type, cache_control):
        self._headers(len(data), content_type, cache_control)
        if self.command != 'HEAD':
            self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=9473)
    parser.add_argument('--cache-dir', type=Path, default=Path('/var/cache/quadra-roblox'))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    cache = Cache(args.cache_dir)
    # Leftovers from a terminated download never become published cache files.
    for path in cache.directory.glob('.download-*.part'):
        path.unlink(missing_ok=True)
    with Server(('127.0.0.1', args.port), cache) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
