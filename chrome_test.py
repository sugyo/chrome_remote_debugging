#!python
#
# Page.addScriptToEvaluateOnNewDocument sample

import datetime
import logging
import os
import re
import subprocess
import time
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
import pychrome


logger = logging.getLogger(__name__)


class ChromeLauncher:
    def __init__(self, headless=False):
        if os.name == 'nt':
            candidate = [
                r'c:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
                r'c:\Program Files\Google\Chrome\Application\chrome.exe',
            ]
        else:
            candidate = []
        self._google_chrome = None
        for google_chrome in candidate:
            if os.path.exists(google_chrome):
                self._google_chrome = google_chrome
                break
        if self._google_chrome is None:
            self._google_chrome = 'google_chrome'
        self._headless = headless
        self._user_data_dir = None
        self._process = None
        self._remote_debugging_url = None

    def start(self):
        if self._process:
            raise RuntimeError('Google chrome is already running')
        if self._user_data_dir is None:
            self._user_data_dir = TemporaryDirectory(prefix='ChromeLauncher')
        logging.info('UserDataDir: {}'.format(self._user_data_dir.name))
        command = [
            self._google_chrome,
            '--enable-logging',
            '--remote-debugging-port=0',
            '--user-data-dir={}'.format(self._user_data_dir.name),
            '--ignore-certificate-errors',
        ]
        if self._headless:
            command.append('--headless')
            command.append('--disable-gpu')

        self._process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            encoding='utf-8',
        )
        while True:
            log = self._process.stderr.readline()
            m = re.search(r'listening on (ws:\S+)', log)
            if m:
                url = 'http://{}'.format(urlparse(m.group(1)).netloc)
                self._remote_debugging_url = url
                break
        logging.info(
            'RemoteDebuggingUrl: {}'.format(self._remote_debugging_url))

    @property
    def remote_debugging_url(self):
        return self._remote_debugging_url

    def wait(self, timeout=None):
        if not self.is_process_running():
            return True
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True

    def is_process_running(self):
        if not self._process:
            return False
        return self._process.returncode is None

    def stop(self):
        self._remote_debugging_url = None
        if self._process:
            if self.is_process_running():
                self._process.terminate()
                try:
                    self._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                self._process.wait()
            time.sleep(1)
            self._process = None
        if self._user_data_dir:
            self._user_data_dir.cleanup()
            self._user_data_dir = None


class ChromeRemoteDebugging:
    def __init__(self):
        self._chrome = None
        self._browser = None
        self._tab = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.stop()

    def start(self):
        if self._browser:
            raise RuntimeError('Browser is already running')
        if self._chrome:
            raise RuntimeError('Google chrome is already running')
        self._chrome = ChromeLauncher()
        self._chrome.start()
        self._browser = pychrome.Browser(self._chrome._remote_debugging_url)
        version = self._browser.version()
        logger.info('Browser: {}, Protocol-Version: {}'.format(
            version['Browser'], version['Protocol-Version']))
        self._tab = self._browser.new_tab()
        self._tab.start()
        self._tab.Page.enable()  # for Page.addScriptToEvaluateOnNewDocument
        self._tab.Network.enable()
        self._tab.Network.responseReceived = self._response_received

    def wait(self, timeout=None):
        self._tab.wait(timeout=timeout)

    def stop(self):
        if self._chrome.is_process_running():
            if self._tab:
                self._tab.stop()
                # self._browser.close_tab(self._tab)
            if self._chrome:
                self._chrome.stop()
        self._tab = None
        self._brawser = None
        self._chrome = None

    def _response_received(self, **kwargs):
        response = kwargs['response']
        if 'url' not in response:
            return
        status = response.get('status', '-')
        url = response['url']
        urlobj = urlparse(url)
        if urlobj.scheme.lower() == 'data':
            return
        timestamp = datetime.timedelta(milliseconds=kwargs['timestamp'])
        logger.info('{}: {} {}'.format(timestamp, url, status))

    def add_script(self, source):
        self._tab.Page.addScriptToEvaluateOnNewDocument(source=source)

    def navigate(self, url):
        self._tab.Page.navigate(url=url)


if __name__ == '__main__':

    import click

    logger.setLevel(logging.DEBUG)

    @click.command()
    @click.option('--url')
    def main(url):
        with ChromeRemoteDebugging() as chrome:
            source = '''
window.addEventListener("beforeunload", function (event) {
  event.preventDefault();
  event.returnValue = '';
});
            '''
            chrome.add_script(source=source)
            if url:
                chrome.navigate(url=url)

            try:
                chrome.wait()
            except KeyboardInterrupt:
                pass

    main()
