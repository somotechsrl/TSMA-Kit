"""WinMM hardware reconnect and an explicit user-owned virtual MIDI output."""
import ctypes as C
from ctypes import wintypes as W
import queue
from core import map_midi

mm = C.WinDLL('winmm')
PTR = C.c_size_t
CALLBACK = C.WINFUNCTYPE(None, W.HANDLE, W.UINT, PTR, PTR, PTR)


class Caps(C.Structure):
    _fields_ = [('mid', W.WORD), ('pid', W.WORD), ('version', W.UINT),
                ('name', W.WCHAR * 32), ('support', W.UINT)]


mm.midiInGetDevCapsW.argtypes = [PTR, C.POINTER(Caps), W.UINT]
mm.midiInOpen.argtypes = [C.POINTER(W.HANDLE), W.UINT, PTR, PTR, W.UINT]
mm.midiInMessage.argtypes = [W.HANDLE, W.UINT, PTR, PTR]
mm.midiInStart.argtypes = mm.midiInStop.argtypes = mm.midiInReset.argtypes = mm.midiInClose.argtypes = [W.HANDLE]
mm.midiOutOpen.argtypes = [C.POINTER(W.HANDLE), W.UINT, PTR, PTR, W.UINT]
mm.midiOutShortMsg.argtypes = [W.HANDLE, W.DWORD]
mm.midiOutReset.argtypes = mm.midiOutClose.argtypes = [W.HANDLE]


def inputs():
    devices = []
    for index in range(mm.midiInGetNumDevs()):
        caps = Caps()
        if mm.midiInGetDevCapsW(index, C.byref(caps), C.sizeof(caps)) == 0:
            devices.append((index, caps.name))
    return devices


def identifier(index):
    # JUCE uses the WinMM device interface string as its stable identifier.
    # mmddk.h: DRV_RESERVED=0x0800; interface size/name = +12/+13.
    size = W.DWORD()
    if mm.midiInMessage(W.HANDLE(index), 0x080C, C.addressof(size), 0) == 0 and size.value:
        buf = C.create_unicode_buffer(size.value // 2)
        if mm.midiInMessage(W.HANDLE(index), 0x080D, C.addressof(buf), size.value) == 0:
            return buf.value
    return dict(inputs()).get(index, '')


class Midi:
    def __init__(self, output_name='TSMA ToneLib'):
        self.name = output_name
        self.opened = {}
        self.output = None
        self.events = queue.Queue()
        self.errors = []
        self.callback = CALLBACK(self.receive)

    def receive(self, handle, message, instance, data, timestamp):
        if message == 0x3C3: self.events.put((instance, data))  # MIM_DATA

    def reconnect(self):
        present = dict(inputs())
        for index, (name, handle) in list(self.opened.items()):
            if present.get(index) != name:
                mm.midiInStop(handle); mm.midiInReset(handle); mm.midiInClose(handle)
                del self.opened[index]
        self.errors = []
        for index, name in present.items():
            folded = name.upper()
            if not any(s in folded for s in ('TSMEGA', 'TONE SHIFTER', 'SINCO', 'CHOCOLATE')): continue
            if index in self.opened: continue
            handle = W.HANDLE()
            result = mm.midiInOpen(C.byref(handle), index, C.cast(self.callback, C.c_void_p).value, index, 0x30000)
            if result:
                self.errors.append(f'{name}: MIDI input busy/error {result}')
            else:
                self.opened[index] = name, handle
                mm.midiInStart(handle)
        # A loopMIDI input/output pair has the same name. Use the input index
        # for JUCE configuration, but enumerate output IDs independently.
        found = None
        for index in range(mm.midiOutGetNumDevs()):
            # MIDIOUTCAPSW is larger than MIDIINCAPSW.
            buf = C.create_string_buffer(128)
            if mm.midiOutGetDevCapsW(index, buf, len(buf)) == 0:
                name = C.wstring_at(C.addressof(buf) + 8, 32).rstrip('\0')
                if name == self.name: found = index; break
        if self.output is not None and found != self.output[0]:
            mm.midiOutReset(self.output[1]); mm.midiOutClose(self.output[1]); self.output = None
        if found is not None and self.output is None:
            handle = W.HANDLE()
            if mm.midiOutOpen(C.byref(handle), found, 0, 0, 0) == 0: self.output = found, handle

    def poll(self, looper):
        while True:
            try: index, data = self.events.get_nowait()
            except queue.Empty: break
            name = self.opened.get(index, ('', None))[0].upper()
            device = 'chocolate' if any(s in name for s in ('SINCO', 'CHOCOLATE')) else 'tsmega'
            for kind, value in map_midi(device, data):
                if kind == 'loop': looper.action(value)
                elif self.output is not None: mm.midiOutShortMsg(self.output[1], value)

    def close(self):
        for _, handle in self.opened.values():
            mm.midiInStop(handle); mm.midiInReset(handle); mm.midiInClose(handle)
        self.opened.clear()
        if self.output is not None:
            mm.midiOutReset(self.output[1]); mm.midiOutClose(self.output[1]); self.output = None
