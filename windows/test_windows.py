"""Offline regressions for Windows MIDI normalization and native OSC controls."""
from pathlib import Path
import socket
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'windows'), str(ROOT / 'bin')]
from core import Looper, map_midi
from osc import decode, encode


class Mappings(unittest.TestCase):
    def test_chocolate_press_release_and_channels(self):
        for index, action in enumerate(('record_play', 'overdub', 'pause', 'clear')):
            for channel in (0, 7, 15):
                self.assertEqual(map_midi('chocolate', 0xB0 + channel | ((80 + index) << 8) | (127 << 16)), [('loop', action)])
                self.assertEqual(map_midi('chocolate', 0xB0 + channel | ((80 + index) << 8)), [])

    def test_ts_navigation_alternating_values_are_both_presses(self):
        for raw, target in ((22, 20), (25, 21)):
            for value in (0, 64, 127):
                messages = map_midi('tsmega', 0xB0 | (raw << 8) | (value << 16))
                self.assertEqual(messages, [('midi', 0xBF | (target << 8) | (127 << 16)), ('midi', 0xBF | (target << 8))])

    def test_ts_page_effect_indices(self):
        for number in range(16):
            result = map_midi('tsmega', 0xC0 | (number << 8))
            self.assertEqual((result[0][1] >> 8) & 127, 24 + number % 8)
            self.assertEqual(result[0][1] & 255, 0xBF)

    def test_irrelevant_messages_do_not_trigger(self):
        for message in (0x7F5090, 0x7F13B0, 0xFAC0):
            self.assertEqual(map_midi('chocolate', message), [])

    def test_native_looper_transitions_reach_osc(self):
        engine = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        engine.bind(('127.0.0.1', 0)); engine.settimeout(1)
        looper = Looper(engine.getsockname()[1])
        try:
            looper.ready = True; looper.state = 0
            looper.action('record_play')
            self.assertEqual(decode(engine.recv(1024)), ('/sl/0/hit', ['record']))
            looper.action('record_play')
            self.assertEqual(decode(engine.recv(1024)), ('/sl/0/hit', ['record']))
            looper.length = 4.
            looper.action('overdub')
            self.assertEqual([decode(engine.recv(1024))[1][0] for _ in range(3)], ['pause_off', 'mute_off', 'overdub'])
            engine.sendto(encode('/update', 0, 'loop_len', 4.), looper.sock.getsockname())
            looper.tick()
            self.assertEqual(looper.length, 4.)
        finally:
            looper.sock.close(); engine.close()


if __name__ == '__main__': unittest.main()
