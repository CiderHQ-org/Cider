"""Which Studio deployment to install and which host to fetch it from."""
import io
import json
import unittest
import urllib.error

from quadra import studio_deploy as deploy

GUID = 'version-7aaa6838d36c4448'


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(json.dumps(data).encode() if not isinstance(data, bytes) else data)

    def __exit__(self, *exc):
        return super().__exit__(*exc)


OPENED = []


def error(url, status):
    failure = urllib.error.HTTPError(url, status, 'failure', {}, io.BytesIO(b'{}'))
    OPENED.append(failure)
    return failure


def tearDownModule():
    for failure in OPENED:
        failure.close()


class Server:
    """Answers by URL; remembers every request with its headers."""

    def __init__(self, answers):
        self.answers, self.requests = answers, []

    def __call__(self, request, timeout=0):
        self.requests.append((request.full_url, dict(request.header_items())))
        answer = self.answers.get(request.full_url)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise error(request.full_url, 404)
        return Response(answer)


class NewestTests(unittest.TestCase):
    def test_the_public_channel_has_no_channel_in_the_address(self):
        server = Server({deploy.VERSION_URL: {'clientVersionUpload': GUID}})
        self.assertEqual(deploy.newest('', '', server), GUID)
        self.assertEqual(deploy.newest('LIVE', '', server), GUID)
        self.assertEqual([url for url, _ in server.requests], [deploy.VERSION_URL] * 2)

    def test_another_channel_is_asked_for_by_name_with_its_token(self):
        url = deploy.VERSION_URL + '/channel/zintegration'
        server = Server({url: {'clientVersionUpload': 'version-b'}})
        self.assertEqual(deploy.newest('zintegration', 'token-1', server), 'version-b')
        self.assertEqual(server.requests[0][1]['Roblox-channel-token'], 'token-1')

    def test_a_channel_that_is_unknown_or_closed_to_the_account_is_named(self):
        url = deploy.VERSION_URL + '/channel/secret'
        with self.assertRaises(deploy.BadChannel) as raised:
            deploy.newest('secret', '', Server({url: error(url, 401)}))
        self.assertEqual(str(raised.exception), 'secret')

    def test_a_refusal_by_the_cdn_host_is_retried_on_roblox_alternate_host(self):
        server = Server({deploy.VERSION_URL: error(deploy.VERSION_URL, 403),
                         deploy.VERSION_ALTERNATE_URL: {'clientVersionUpload': GUID}})
        self.assertEqual(deploy.newest('', '', server), GUID)

    def test_other_failures_are_not_hidden(self):
        with self.assertRaises(urllib.error.HTTPError):
            deploy.newest('', '', Server({deploy.VERSION_URL: error(deploy.VERSION_URL, 500)}))

    def test_a_cdn_host_that_cannot_be_reached_falls_back_too(self):
        server = Server({deploy.VERSION_URL: urllib.error.URLError('unreachable'),
                         deploy.VERSION_ALTERNATE_URL: {'clientVersionUpload': GUID}})
        self.assertEqual(deploy.newest('', '', server), GUID)


class ResolveTests(unittest.TestCase):
    def test_a_pinned_version_needs_no_network(self):
        server = Server({})
        self.assertEqual(deploy.resolve('version-aa', 'zintegration', lambda: 'cookie', server),
                         ('version-aa', 'zintegration'))
        self.assertEqual(server.requests, [])

    def test_a_named_channel_is_used_as_it_is_and_the_sign_in_is_not_read(self):
        server = Server({deploy.VERSION_URL + '/channel/zbeta': {'clientVersionUpload': 'version-c'}})
        cookie = lambda: self.fail('the sign-in is only needed for the account channel')
        self.assertEqual(deploy.resolve('', 'zbeta', cookie, server), ('version-c', 'zbeta'))

    def test_without_a_sign_in_the_public_channel_is_used(self):
        server = Server({deploy.VERSION_URL: {'clientVersionUpload': GUID}})
        self.assertEqual(deploy.resolve('', '', lambda: None, server), (GUID, ''))
        self.assertEqual(len(server.requests), 1)

    def test_a_signed_in_account_gets_its_own_channel_with_the_token_but_the_cookie_goes_only_to_roblox(self):
        server = Server({
            deploy.USER_CHANNEL_URL: {'channel': 'zstaff', 'token': 'tok'},
            deploy.VERSION_URL + '/channel/zstaff': {'clientVersionUpload': 'version-d'}})
        self.assertEqual(deploy.resolve('', '', lambda: 'SECRET', server), ('version-d', 'zstaff'))
        by_url = dict(server.requests)
        self.assertEqual(by_url[deploy.USER_CHANNEL_URL]['Cookie'], '.ROBLOSECURITY=SECRET')
        self.assertEqual(by_url[deploy.VERSION_URL + '/channel/zstaff']['Roblox-channel-token'], 'tok')
        self.assertNotIn('Cookie', by_url[deploy.VERSION_URL + '/channel/zstaff'])

    def test_when_roblox_cannot_name_the_accounts_channel_the_public_one_is_used(self):
        server = Server({deploy.USER_CHANNEL_URL: urllib.error.URLError('down'),
                         deploy.VERSION_URL: {'clientVersionUpload': GUID}})
        self.assertEqual(deploy.resolve('', '', lambda: 'SECRET', server), (GUID, ''))


class PackageTests(unittest.TestCase):
    def test_the_public_channel_uses_the_plain_path_and_others_the_common_one(self):
        self.assertEqual(deploy.package_urls(GUID, '', 'a.zip')[0], f'https://setup.rbxcdn.com/{GUID}-a.zip')
        self.assertEqual(deploy.package_urls(GUID, 'zbeta', 'a.zip')[0],
                         f'https://setup.rbxcdn.com/channel/common/{GUID}-a.zip')

    def test_robloxs_own_alternate_hosts_follow_the_main_one(self):
        hosts = [url.split('/')[2] for url in deploy.package_urls(GUID, '', 'a.zip')]
        self.assertEqual(hosts, ['setup.rbxcdn.com', 'setup-aws.rbxcdn.com', 'setup-ak.rbxcdn.com', 's3.amazonaws.com'])


class OpenFirstTests(unittest.TestCase):
    urls = ['https://one/x', 'https://two/x', 'https://three/x']

    def opener(self, behaviour):
        calls = []

        def opener(request, timeout=0):
            calls.append(request.full_url)
            outcome = behaviour[request.full_url]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        opener.calls = calls
        return opener

    def test_the_first_host_that_answers_is_used(self):
        opener = self.opener({self.urls[0]: error(self.urls[0], 403), self.urls[1]: 'two says hi'})
        self.assertEqual(deploy.open_first(self.urls, opener), 'two says hi')
        self.assertEqual(opener.calls, self.urls[:2])

    def test_every_refusal_and_failure_moves_on(self):
        for status in (403, 404, 408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                opener = self.opener({self.urls[0]: error(self.urls[0], status), self.urls[1]: 'ok'})
                self.assertEqual(deploy.open_first(self.urls, opener), 'ok')
        for failure in (urllib.error.URLError('x'), TimeoutError(), ConnectionResetError()):
            with self.subTest(failure=failure):
                opener = self.opener({self.urls[0]: failure, self.urls[1]: 'ok'})
                self.assertEqual(deploy.open_first(self.urls, opener), 'ok')

    def test_an_answer_that_is_not_about_availability_is_not_retried(self):
        opener = self.opener({self.urls[0]: error(self.urls[0], 401), self.urls[1]: 'ok'})
        with self.assertRaises(urllib.error.HTTPError):
            deploy.open_first(self.urls, opener)
        self.assertEqual(opener.calls, self.urls[:1])

    def test_when_every_host_fails_the_last_failure_is_raised(self):
        opener = self.opener({url: error(url, 503) for url in self.urls})
        with self.assertRaises(urllib.error.HTTPError) as raised:
            deploy.open_first(self.urls, opener)
        self.assertEqual(raised.exception.code, 503)
        self.assertEqual(opener.calls, self.urls)


if __name__ == '__main__':
    unittest.main()
