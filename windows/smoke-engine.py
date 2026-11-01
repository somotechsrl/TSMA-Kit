"""Exercise the bundled Cygwin engine via real native Windows JACK and OSC.

Dummy audio only: the CI test never opens a physical microphone or speaker.
"""
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'windows'), str(ROOT / 'bin')]
from core import Looper
from winjack import jack_directory


def main():
    engine = ROOT / 'dist' / 'windows' / 'engine'
    env = os.environ.copy(); env['PATH'] = str(engine) + os.pathsep + env['PATH']
    processes = []
    looper = Looper()
    def wait(predicate, seconds=10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            looper.tick()
            if predicate(): return
            time.sleep(.03)
        raise AssertionError(f'Engine state={looper.state}, length={looper.length}, ready={looper.ready}')
    try:
        processes.append(subprocess.Popen([str(jack_directory() / 'jackd.exe'), '-d', 'dummy', '-r', '48000', '-p', '256']))
        time.sleep(2)
        processes.append(subprocess.Popen([str(engine / 'sooperlooper.exe'), '-j', 'TSMA_Looper', '-p', '19951', '-l', '1', '-c', '2', '-t', '10', '-D', 'no'], env=env))
        wait(lambda: looper.ready and looper.state == 0)
        assert looper.action('record_play')
        wait(lambda: looper.state in (2, 3))
        time.sleep(.4)
        assert looper.action('record_play')
        wait(lambda: looper.state == 4 and looper.length > .1)
        assert looper.action('overdub')
        wait(lambda: looper.state == 5)
        assert looper.action('overdub')
        wait(lambda: looper.state == 4)
        assert looper.action('pause')
        wait(lambda: looper.state == 14)
        assert looper.action('clear')
        wait(lambda: looper.state == 0 or looper.length == 0.)
        print('PASS: Windows JACK + Cygwin SooperLooper OSC record/play/overdub/pause/clear')
    finally:
        looper.sock.close()
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=5)
                except subprocess.TimeoutExpired: p.kill()


if __name__ == '__main__': main()
