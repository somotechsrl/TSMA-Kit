"""Windows-independent MIDI mapping and OSC looper client.

The looper command transitions are shared with the Linux application.
"""
import queue
import socket
import time
from controls import transition
from osc import decode, encode


def map_midi(device, message):
    status, data1, data2 = message & 255, (message >> 8) & 127, (message >> 16) & 127
    kind = status & 240
    if device == 'chocolate' and kind == 176 and data2 > 0 and 80 <= data1 <= 83:
        return [('loop', ('record_play', 'overdub', 'pause', 'clear')[data1 - 80])]
    if device != 'tsmega':
        return []
    if kind == 192:
        cc = 24 + data1 % 8
    elif kind == 176 and data1 in (22, 25):
        # The hardware alternates values. Both values are real presses.
        cc = 20 if data1 == 22 else 21
    else:
        return []
    return [('midi', 191 | (cc << 8) | (127 << 16)), ('midi', 191 | (cc << 8))]


class Looper:
    def __init__(self, port=19951):
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.setblocking(False)
        self.url = f'osc.udp://127.0.0.1:{self.sock.getsockname()[1]}/'
        self.ready = False
        self.state, self.length, self.position = -1, 0., 0.
        self.last_ping = self.last_reply = 0.
        self.save_at = None
        self.events = queue.Queue()

    def send(self, path, *args):
        self.sock.sendto(encode(path, *args), ('127.0.0.1', self.port))

    def hit(self, command):
        self.send('/sl/0/hit', command)

    def tick(self):
        now = time.monotonic()
        if now - self.last_reply > 3:
            self.ready = False
        if now - self.last_ping > 1:
            self.send('/ping', self.url, '/pong')
            self.last_ping = now
        while True:
            try:
                path, args = decode(self.sock.recv(65536))
            except BlockingIOError:
                break
            except ConnectionResetError:
                # Windows reports an ICMP port-unreachable response while the
                # owned engine is starting. Retry the ping on the next tick.
                break
            except (ValueError, IndexError, UnicodeError):
                continue
            if path == '/pong':
                self.last_reply = now
                if not self.ready:
                    self.setup()
            elif path == '/update' and len(args) >= 3:
                if args[1] == 'state': self.state = int(args[2])
                elif args[1] == 'loop_len': self.length = float(args[2])
                elif args[1] == 'loop_pos': self.position = float(args[2])
            elif path == '/error':
                self.events.put(str(args))

    def setup(self):
        for name, value in {'dry': 1., 'wet': 1., 'input_gain': 1., 'auto_disable_latency': 1.}.items():
            self.send('/set', name, value)
        for name, value in {'dry': 0., 'wet': 1., 'input_gain': 1., 'feedback': 1.,
                            'rec_thresh': 0., 'quantize': 0., 'round': 0., 'sync': 0.,
                            'playback_sync': 0., 'use_common_ins': 1., 'use_common_outs': 1.,
                            'fade_samples': 64.}.items():
            self.send('/sl/0/set', name, value)
        for name in ('state', 'loop_len', 'loop_pos'):
            self.send('/sl/0/register_auto_update', name, 40, self.url, '/update')
            self.send('/sl/0/get', name, self.url, '/update')
        self.ready = True

    def action(self, action):
        if not self.ready or self.state < 0: return False
        commands, self.state, save = transition(action, self.state, self.length)
        for command in commands: self.hit(command)
        if action == 'clear': self.length = 0.
        if save: self.save_at = time.monotonic() + .7
        return True

    def save(self, path):
        if not self.ready or self.state in (1, 2, 3, 5): return False
        self.send('/save_session', str(path), self.url, '/error', 1)
        self.save_at = None
        return True
