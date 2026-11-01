"""Native JACK client and conservative routing of the kit's own ports."""
import ctypes as C
import os
from pathlib import Path
import re


def jack_directory():
    candidates = []
    for key in ('ProgramFiles', 'ProgramFiles(x86)'):
        base = Path(os.environ.get(key, 'C:/Program Files'))
        candidates += [base / 'JACK2', base / 'Jack', base / 'JACK2' / 'bin', base / 'Jack' / 'bin']
    for candidate in candidates:
        if (candidate / 'jackd.exe').is_file(): return candidate
    raise RuntimeError('Install the official JACK2 64-bit Windows package first. See Windows setup instructions.')


class Jack:
    def __init__(self):
        directory = jack_directory()
        self.dll_dirs = [os.add_dll_directory(str(directory))]
        dlls = [directory / 'libjack64.dll', Path(os.environ.get('WINDIR', 'C:/Windows')) / 'libjack64.dll']
        dll = next((p for p in dlls if p.exists()), None)
        if dll is None: raise RuntimeError('Native JACK client DLL was not found.')
        self.lib = C.CDLL(str(dll))
        self.lib.jack_client_open.argtypes = [C.c_char_p, C.c_uint, C.POINTER(C.c_uint)]
        self.lib.jack_client_open.restype = C.c_void_p
        self.lib.jack_client_close.argtypes = [C.c_void_p]
        self.lib.jack_get_sample_rate.argtypes = [C.c_void_p]
        self.lib.jack_get_ports.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p, C.c_ulong]
        self.lib.jack_get_ports.restype = C.POINTER(C.c_char_p)
        self.lib.jack_free.argtypes = [C.c_void_p]
        self.lib.jack_port_by_name.argtypes = [C.c_void_p, C.c_char_p]
        self.lib.jack_port_by_name.restype = C.c_void_p
        self.lib.jack_port_flags.argtypes = [C.c_void_p]
        self.lib.jack_port_get_all_connections.argtypes = [C.c_void_p, C.c_void_p]
        self.lib.jack_port_get_all_connections.restype = C.POINTER(C.c_char_p)
        for fn in ('jack_connect', 'jack_disconnect'):
            getattr(self.lib, fn).argtypes = [C.c_void_p, C.c_char_p, C.c_char_p]
        self.client = None
        self.lost = False
        callback = C.CFUNCTYPE(None, C.c_void_p)
        self.shutdown_callback = callback(self.shutdown)
        self.lib.jack_on_shutdown.argtypes = [C.c_void_p, callback, C.c_void_p]

    def shutdown(self, _):
        self.lost = True

    def connect(self):
        if self.lost:
            self.close(); self.lost = False
        if self.client: return True
        status = C.c_uint()
        self.client = self.lib.jack_client_open(b'TSMA_Control', 1, C.byref(status))
        if self.client: self.lib.jack_on_shutdown(self.client, self.shutdown_callback, None)
        return bool(self.client)

    @staticmethod
    def strings(ptr):
        if not ptr: return []
        result, index = [], 0
        while ptr[index]:
            result.append(ptr[index].decode('utf-8', errors='replace')); index += 1
        return result

    def ports(self, flags=0):
        ptr = self.lib.jack_get_ports(self.client, None, b'32 bit float mono audio', flags)
        try: return self.strings(ptr)
        finally:
            if ptr: self.lib.jack_free(ptr)

    def peers(self, name):
        port = self.lib.jack_port_by_name(self.client, name.encode())
        if not port: return []
        ptr = self.lib.jack_port_get_all_connections(self.client, port)
        try: return self.strings(ptr)
        finally:
            if ptr: self.lib.jack_free(ptr)

    def route(self):
        if not self.connect(): return 'Waiting for JACK'
        if self.lib.jack_get_sample_rate(self.client) != 48000:
            return 'JACK must run at 48000 Hz; audio routing is paused'
        ins, outs = self.ports(1), self.ports(2)
        clients = {p.split(':')[0] for p in ins if re.search(r'tonelib|juce', p, re.I)}
        if len(clients) != 1: return 'Waiting for ToneLib JACK/JackRouter audio ports'
        client = next(iter(clients)) + ':'
        gi = sorted(p for p in ins if p.startswith(client))[:2]
        go = sorted(p for p in outs if p.startswith(client))[:2]
        li = [f'TSMA_Looper:common_in_{n}' for n in (1, 2)]
        lo = [f'TSMA_Looper:common_out_{n}' for n in (1, 2)]
        capture = [p for p in self.ports(2 | 4) if p.startswith('system:')]
        playback = [p for p in self.ports(1 | 4) if p.startswith('system:')]
        ardour = sorted(p for p in ins if re.search(r'ardour.*:TSMA-Kit/.*in', p, re.I))[:2]
        destination = ardour if len(ardour) == 2 else playback[:2]
        if len(gi) != 2 or len(go) != 2 or not capture or len(destination) != 2:
            return 'Waiting for stereo audio ports'
        desired = [(capture[0], p) for p in gi]
        desired += list(zip(go, li)) + list(zip(lo, destination))
        desired = [(a, b) for a, b in desired if a in outs and b in ins]
        # Own only ToneLib inputs, SooperLooper inputs, and ToneLib/looper
        # outputs. Remove JackRouter's auto-connections that bypass the looper.
        for a, b in desired:
            for old in self.peers(b):
                if b in gi + li and (old, b) not in desired:
                    self.lib.jack_disconnect(self.client, old.encode(), b.encode())
            if b not in self.peers(a): self.lib.jack_connect(self.client, a.encode(), b.encode())
        for source in go + lo:
            if source not in outs: continue
            for target in self.peers(source):
                if (source, target) not in desired:
                    self.lib.jack_disconnect(self.client, source.encode(), target.encode())
        return 'Audio connected' if len(desired) == 6 else 'Waiting for SooperLooper audio ports'

    def close(self):
        if self.client:
            self.lib.jack_client_close(self.client); self.client = None
