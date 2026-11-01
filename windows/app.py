"""Experimental Windows 10/11 x64 performance container.

JACK/JackRouter, ToneLib and an explicit loopMIDI port are first-run prerequisites.
This program never launches Ardour and never copies a ToneLib registration.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser
from core import Looper

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
DATA = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'TSMA-Kit'
NO_WINDOW = 0x08000000


def self_test():
    from core import map_midi
    assert map_midi('chocolate', 0x7F50B0) == [('loop', 'record_play')]
    assert map_midi('chocolate', 0x0050B0) == []
    assert map_midi('tsmega', 0x0016B0) == map_midi('tsmega', 0x4016B0)
    assert (BASE / 'engine' / 'sooperlooper.exe').is_file()
    import winmidi
    winmidi.inputs()
    root = tk.Tk(); root.withdraw(); root.update(); root.destroy()
    (DATA / 'self-test.ok').write_text('Windows application, Tcl/Tk, WinMM and OSC checks passed.\n')


def cygpath(path):
    path = Path(path).resolve().as_posix()
    return '/cygdrive/' + path[0].lower() + path[2:] if len(path) > 1 and path[1] == ':' else path


class App:
    def __init__(self, root):
        self.root = root
        self.root.title('TSMA Kit — Windows preview')
        self.root.geometry('1280x900')
        self.root.minsize(800, 620)
        self.root.configure(bg='#52606d')
        icon = BASE / 'tsma-kit.ico'
        if icon.exists(): root.iconbitmap(str(icon))
        self.config_path = DATA / 'settings.json'
        try: self.settings = json.loads(self.config_path.read_text())
        except (OSError, ValueError): self.settings = {}
        self.owned = []
        self.log = (DATA / 'kit.log').open('a', buffering=1)
        self.looper = Looper()
        self.jack = self.midi = None
        self.tone = self.engine = None
        self.hwnd = None
        self.original_window = None
        self.running = False
        self.next_slow = 0.
        self.session = DATA / 'state' / 'looper.slsess'
        self.session.parent.mkdir(exist_ok=True)
        header = tk.Frame(root, bg='#20252b', padx=12, pady=8)
        header.pack(fill='x', padx=1, pady=(1, 0))
        tk.Label(header, text='TSMA KIT', fg='white', bg='#20252b', font=('Segoe UI', 13, 'bold')).pack(side='left')
        for title, command in [('Setup', self.setup), ('Drums', self.drums)]:
            ttk.Button(header, text=title, command=command).pack(side='right', padx=4)
        self.host = tk.Frame(root, bg='#11151a')
        self.host.pack(fill='both', expand=True, padx=1)
        self.host.bind('<Configure>', lambda _: self.resize())
        self.placeholder = tk.Label(self.host, text='Windows experimental build\nComplete Setup to start the rig.',
                                    fg='#c5d0dc', bg='#11151a', font=('Segoe UI', 16))
        self.placeholder.pack(expand=True)
        bottom = tk.Frame(root, bg='#20252b', padx=12, pady=10)
        bottom.pack(fill='x', padx=1, pady=(0, 1))
        self.loop_status = tk.StringVar(value='SooperLooper — stopped')
        tk.Label(bottom, textvariable=self.loop_status, fg='white', bg='#20252b', font=('Segoe UI', 12)).pack(anchor='w')
        self.progress = ttk.Progressbar(bottom, maximum=1.)
        self.progress.pack(fill='x', pady=8)
        buttons = tk.Frame(bottom, bg='#20252b'); buttons.pack(fill='x')
        for i, (title, action) in enumerate([('A · Rec / Play', 'record_play'), ('B · Overdub', 'overdub'),
                                           ('C · Pause', 'pause'), ('D · Clear', 'clear')]):
            buttons.columnconfigure(i, weight=1)
            ttk.Button(buttons, text=title, command=lambda a=action: self.looper.action(a)).grid(row=0, column=i, sticky='ew', padx=4, ipady=8)
        self.status = tk.StringVar(value='Not started')
        tk.Label(bottom, textvariable=self.status, fg='#bac9d9', bg='#20252b', anchor='w').pack(fill='x', pady=(8, 0))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(200, self.setup if not self.settings else self.start)
        self.root.after(40, self.tick)

    def spawn(self, args, **kw):
        env = os.environ.copy()
        # Keep the Cygwin dependency DLLs private to the owned engine process.
        env['PATH'] = str(BASE / 'engine') + os.pathsep + env.get('PATH', '')
        p = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT,
                             creationflags=NO_WINDOW, env=env, **kw)
        self.owned.append(p)
        return p

    def setup(self):
        if self.running:
            messagebox.showinfo('TSMA Kit', 'Close and reopen the kit before changing its audio/MIDI setup.'); return
        dialog = tk.Toplevel(self.root); dialog.title('TSMA Kit — first-run setup')
        frame = ttk.Frame(dialog, padding=16); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Windows preview: audio and pedal hardware have not been validated.\n'
                             'Install ToneLib GFX, JACK2 x64 (including JackRouter) and loopMIDI.\n'
                             'Create a loopMIDI port named TSMA ToneLib; keep loopMIDI running.').grid(row=0, column=0, columnspan=3, sticky='w', pady=8)
        for i, (name, url) in enumerate([('ToneLib', 'https://tonelib.net/downloads.html'),
                                       ('JACK2', 'https://jackaudio.org/downloads/'),
                                       ('loopMIDI', 'https://www.tobias-erichsen.de/software/loopmidi.html')]):
            ttk.Button(frame, text=name, command=lambda u=url: webbrowser.open(u)).grid(row=1, column=i, sticky='ew', padx=4)
        path = tk.StringVar(value=self.settings.get('tonelib', ''))
        device = tk.StringVar(value=self.settings.get('audio_device', ''))
        ttk.Label(frame, text='ToneLib GFX executable:').grid(row=2, column=0, sticky='w', pady=(16, 4))
        ttk.Entry(frame, textvariable=path, width=65).grid(row=3, column=0, columnspan=2, sticky='ew')
        def browse():
            p = filedialog.askopenfilename(parent=dialog, filetypes=[('Windows application', '*.exe')])
            if p: path.set(p)
        ttk.Button(frame, text='Browse…', command=browse).grid(row=3, column=2)
        ttk.Label(frame, text='Exact JACK PortAudio device name (Tone Shifter, not JackRouter):').grid(row=4, column=0, columnspan=3, sticky='w', pady=(16, 4))
        ttk.Entry(frame, textvariable=device, width=65).grid(row=5, column=0, columnspan=2, sticky='ew')
        def list_devices():
            try:
                from winjack import jack_directory
                result = subprocess.run([str(jack_directory() / 'jackd.exe'), '-d', 'portaudio', '-l'],
                                        capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
                window = tk.Toplevel(dialog); window.title('JACK audio devices — copy the exact Tone Shifter device name')
                text = tk.Text(window, width=100, height=25); text.pack(fill='both', expand=True)
                text.insert('1.0', result.stdout + result.stderr)
            except Exception as exc: messagebox.showerror('JACK devices', str(exc), parent=dialog)
        ttk.Button(frame, text='List devices', command=list_devices).grid(row=5, column=2)
        reuse = tk.BooleanVar(value=self.settings.get('reuse_jack', False))
        ttk.Checkbutton(frame, text='Use an already-running JACK server instead (48 kHz, input L, stereo output)', variable=reuse).grid(row=6, column=0, columnspan=3, sticky='w', pady=12)
        ttk.Label(frame, text='A fresh ToneLib profile imports the kit presets and selects ASIO / JackRouter.\n'
                             'Existing ToneLib settings are preserved: select JackRouter and enable only\n'
                             'TSMA ToneLib in ToneLib MIDI inputs yourself. Your license remains yours.').grid(row=7, column=0, columnspan=3, sticky='w', pady=8)
        def save():
            if not Path(path.get()).is_file():
                messagebox.showerror('Setup', 'Select the installed ToneLib executable.', parent=dialog); return
            if not reuse.get() and not device.get().strip():
                messagebox.showerror('Setup', 'Select the exact Tone Shifter audio device or use an existing JACK server.', parent=dialog); return
            self.settings = {'tonelib': path.get(), 'audio_device': device.get().strip(), 'reuse_jack': reuse.get()}
            self.config_path.write_text(json.dumps(self.settings, indent=2)); dialog.destroy(); self.start()
        ttk.Button(frame, text='Save and start', command=save).grid(row=8, column=0, columnspan=3, pady=12)

    def start(self):
        if self.running: return
        try:
            from winjack import Jack, jack_directory
            from winmidi import Midi, identifier, inputs
            from winprofile import install
            self.jack = Jack()
            if not self.jack.connect():
                if self.settings.get('reuse_jack'):
                    raise RuntimeError('Start your configured JACK server before starting the kit.')
                device = self.settings.get('audio_device', '')
                if not device: raise RuntimeError('Choose the Tone Shifter audio device in Setup.')
                self.spawn([str(jack_directory() / 'jackd.exe'), '-R', '-S', '-d', 'portaudio',
                            '-d', device, '-r', '48000', '-p', '256', '-i', '2', '-o', '2'])
                deadline = time.monotonic() + 10
                while not self.jack.connect() and time.monotonic() < deadline: time.sleep(.2)
            if not self.jack.client: raise RuntimeError('JACK did not start. Check the audio device and kit.log.')
            self.midi = Midi(); self.midi.reconnect()
            virtual = next((identifier(i) for i, name in inputs() if name == 'TSMA ToneLib'), '')
            install(BASE, virtual)
            args = [str(BASE / 'engine' / 'sooperlooper.exe'), '-j', 'TSMA_Looper', '-p', '19951',
                    '-l', '1', '-c', '2', '-t', '300', '-D', 'no']
            if self.session.exists(): args += ['-L', cygpath(self.session)]
            self.engine = self.spawn(args, cwd=DATA)
            self.tone = self.spawn([self.settings['tonelib']], cwd=DATA)
            self.started = time.monotonic()
            self.running = True
        except Exception as exc:
            self.stop()
            messagebox.showerror('TSMA Kit could not start', str(exc))
            self.status.set('Setup required; see kit.log')

    def embed(self):
        if self.hwnd or not self.tone or self.tone.poll() is not None: return
        user = C.windll.user32
        callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        found = []
        user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
        user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        user.EnumWindows.argtypes = [callback_type, W.LPARAM]
        @callback_type
        def visit(hwnd, _):
            pid = W.DWORD(); user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            title = C.create_unicode_buffer(256); user.GetWindowTextW(hwnd, title, len(title))
            if pid.value == self.tone.pid and 'tonelib' in title.value.lower() and user.IsWindowVisible(hwnd): found.append(hwnd)
            return True
        user.EnumWindows(visit, 0)
        if not found: return
        hwnd = found[0]
        user.GetWindowLongPtrW.argtypes = [W.HWND, C.c_int]
        user.GetWindowLongPtrW.restype = C.c_ssize_t
        user.SetWindowLongPtrW.argtypes = [W.HWND, C.c_int, C.c_ssize_t]
        user.SetWindowLongPtrW.restype = C.c_ssize_t
        user.SetParent.argtypes = [W.HWND, W.HWND]; user.SetParent.restype = W.HWND
        self.original_window = user.GetWindowLongPtrW(hwnd, -16)
        C.set_last_error(0)
        old = user.SetParent(hwnd, self.host.winfo_id())
        if not old and C.get_last_error():
            self.status.set('ToneLib could not be embedded; its external window remains available'); return
        user.SetWindowLongPtrW(hwnd, -16, (self.original_window & ~0x80C40000) | 0x40000000)
        self.hwnd = hwnd
        self.placeholder.pack_forget()
        self.resize()

    def resize(self):
        if self.hwnd:
            user = C.windll.user32
            user.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
            user.SetWindowPos(self.hwnd, 0, 0, 0, self.host.winfo_width(), self.host.winfo_height(), 0x0034)

    def drums(self):
        folder = DATA / 'BackingTracks' / 'Drums'; folder.mkdir(parents=True, exist_ok=True)
        # Explorer provides the normal native file drop onto ToneLib's player.
        os.startfile(str(folder))

    def tick(self):
        try:
            now = time.monotonic()
            self.looper.tick()
            if self.running:
                if self.midi: self.midi.poll(self.looper)
                self.embed()
                if self.looper.ready and self.session.exists() and not getattr(self, 'restored', False):
                    self.looper.hit('pause_on'); self.restored = True
                if self.looper.save_at is not None and now >= self.looper.save_at: self.looper.save(cygpath(self.session))
                if now >= self.next_slow:
                    self.next_slow = now + 1
                    self.midi.reconnect()
                    status = self.jack.route()
                    if self.midi.output is None: status += ' · TSMA ToneLib virtual MIDI port missing'
                    if self.midi.errors: status += ' · ' + '; '.join(self.midi.errors)
                    self.status.set(status)
                if self.engine.poll() is not None or self.tone.poll() is not None:
                    self.status.set('An application stopped. Close and restart the kit; see kit.log.')
                names = {0: 'Empty', 2: 'Recording', 3: 'Recording', 4: 'Playing', 5: 'Overdub', 14: 'Paused'}
                self.loop_status.set(f'SooperLooper · {names.get(self.looper.state, "Waiting")} · {self.looper.length:.1f} s')
                self.progress['value'] = self.looper.position / self.looper.length if self.looper.length > 0 else 0
            while True:
                try: self.log.write(self.looper.events.get_nowait() + '\n')
                except queue.Empty: break
        except Exception as exc:
            self.status.set(str(exc)); self.log.write(repr(exc) + '\n')
        self.root.after(40, self.tick)

    def stop(self):
        self.running = False
        if self.looper.ready:
            if self.looper.state in (2, 3, 5): self.looper.action('pause'); time.sleep(.1)
            self.looper.save(cygpath(self.session)); time.sleep(.5)
        if self.midi: self.midi.close(); self.midi = None
        if self.jack: self.jack.close(); self.jack = None
        # Only processes started by this instance belong to it.
        for process in reversed(self.owned):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill()
        self.owned.clear()

    def close(self):
        self.stop(); self.looper.sock.close(); self.log.close(); self.root.destroy()


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    if '--self-test' in sys.argv: self_test(); return
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
    kernel.CreateMutexW.restype = W.HANDLE
    mutex = kernel.CreateMutexW(None, False, 'Local\\TSMA-Kit')
    if C.get_last_error() == 183: return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__': main()
