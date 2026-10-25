"""What Discord shows while Studio runs, from the lines of Studio's own log."""
import unittest
from unittest.mock import Mock, patch

from quadra import discord, studio_presence
from quadra.studio_presence import StudioPresence


class Immediate:
    """A thread that runs when started: the place lookup finishes before the next line."""

    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


PLACE = '0024:warn:seh:dispatch_exception "2026-10-25T16:31:16.898Z,0.8,0124,6 [FLog::CloseDataModel] Setting place ID %d"'
DOCUMENT = '0024:warn:seh:dispatch_exception "2026-10-25T16:31:17.000Z,0.9,0124,6 [FLog::RobloxDocManager] Setting current doc to type %s"'


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.rpc = Mock()
        self.info = {'name': 'Obby Builder', 'icon_url': 'https://t.test/icon.png', 'place_id': 7}
        self.fetch = Mock(return_value=self.info)
        self.now = [1000.0]
        patcher = patch.object(studio_presence.threading, 'Thread', Immediate)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.presence = StudioPresence(self.rpc, self.fetch, clock=lambda: self.now[0])

    def shown(self):
        return self.rpc.queue_presence.call_args.kwargs

    def test_an_idle_studio_says_so_with_the_logo(self):
        self.presence.feed(DOCUMENT % '-1')
        self.assertEqual(self.shown()['details'], 'Idling')
        self.assertEqual(self.shown()['large_image'], discord.LOGO)
        self.assertEqual(self.shown()['large_text'], 'Quadra Studio')

    def test_an_open_place_shows_its_name_and_icon_from_the_moment_it_was_opened(self):
        self.presence.feed(DOCUMENT % '-1')
        self.now[0] = 2000.0
        self.presence.feed(PLACE % 7)
        self.presence.feed(DOCUMENT % '0')
        self.fetch.assert_called_once_with(7)
        shown = self.shown()
        self.assertEqual(shown['details'], 'Developing Obby Builder')
        self.assertEqual(shown['large_image'], 'https://t.test/icon.png')
        self.assertEqual(shown['start_time'], 2000.0)
        self.assertIsNone(shown['state'])

    def test_a_script_in_front_is_named_without_losing_the_place(self):
        self.presence.feed(PLACE % 7)
        self.presence.feed(DOCUMENT % '0')
        self.presence.feed(DOCUMENT % '2')
        self.assertEqual(self.shown()['details'], 'Developing Obby Builder')
        self.assertEqual(self.shown()['state'], 'Editing a script')
        self.presence.feed(DOCUMENT % '0')
        self.assertIsNone(self.shown()['state'])

    def test_closing_the_place_goes_back_to_idling_with_a_fresh_clock(self):
        self.presence.feed(PLACE % 7)
        self.presence.feed(DOCUMENT % '0')
        self.now[0] = 3000.0
        self.presence.feed(DOCUMENT % '-1')
        self.assertEqual((self.shown()['details'], self.shown()['start_time']), ('Idling', 3000.0))
        self.presence.feed(PLACE % 7)
        self.assertEqual(self.fetch.call_count, 2, 'the same place opened again is looked up again')

    def test_a_place_that_cannot_be_looked_up_is_shown_without_a_name(self):
        self.fetch.side_effect = OSError('offline')
        self.presence.feed(PLACE % 9)
        self.presence.feed(DOCUMENT % '0')
        self.assertEqual(self.shown()['details'], 'Developing a place')
        self.assertEqual(self.shown()['large_image'], discord.LOGO)

    def test_the_same_line_arriving_three_times_is_one_update(self):
        for _ in range(3):
            self.presence.feed(PLACE % 7)
            self.presence.feed(DOCUMENT % '0')
        self.assertEqual(self.fetch.call_count, 1)
        # one for the place resolving (named) and the document change before it (unnamed)
        self.assertLessEqual(self.rpc.queue_presence.call_count, 2)

    def test_other_lines_and_unknown_document_types_change_nothing(self):
        for line in ('0024:warn:seh:OutputDebugStringA "something else"', DOCUMENT % '9', '', 'FLog::Output',
                     '[FLog::CloseDataModel] Create DataModel - heartbeat(1)'):
            self.presence.feed(line)
        self.rpc.queue_presence.assert_not_called()

    def test_closing_clears_the_presence_and_waits_for_the_connection_worker(self):
        self.rpc._worker = Mock()
        self.presence.close(wait=5)
        self.rpc.close.assert_called_once()
        self.rpc._worker.join.assert_called_once_with(5)

    def test_a_late_answer_for_a_place_that_was_left_is_ignored(self):
        answers = {}

        def lookup(place_id):
            return answers[place_id]

        class Deferred(Immediate):
            pending = []

            def start(self):
                Deferred.pending.append(self)

        with patch.object(studio_presence.threading, 'Thread', Deferred):
            presence = StudioPresence(self.rpc, lookup, clock=lambda: 1.0)
            answers.update({1: {'name': 'First'}, 2: {'name': 'Second'}})
            presence.feed(PLACE % 1)
            presence.feed(PLACE % 2)
            presence.feed(DOCUMENT % '0')
            for thread in list(Deferred.pending):
                thread.target(*thread.args)
        self.assertEqual(self.shown()['details'], 'Developing Second')


if __name__ == '__main__':
    unittest.main()
