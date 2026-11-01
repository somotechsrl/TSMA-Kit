#!/usr/bin/env python3
"""Collect exact Cygwin runtime source archives and their published SHA-512s."""
import hashlib
import json
import lzma
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MIRROR = 'https://mirrors.kernel.org/sourceware/cygwin/'


def main():
    sources = ROOT / '.cache-build' / 'windows' / 'sources'
    sources.mkdir(parents=True, exist_ok=True)
    index = lzma.decompress(urllib.request.urlopen(MIRROR + 'x86_64/setup.xz').read()).decode()
    sections = {}
    for section in re.split(r'(?m)^@ ', index)[1:]:
        name, _, body = section.partition('\n'); sections[name] = body
    installed = {}
    for line in Path('C:/cygwin/etc/setup/installed.db').read_text().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2: installed[parts[0]] = parts[1]
    packages = set()
    for dll in (ROOT / 'dist/windows/engine').glob('cyg*.dll'):
        output = subprocess.check_output(['C:/cygwin/bin/cygcheck.exe', '-f', '/usr/bin/' + dll.name], text=True).strip()
        matches = [name for name, archive in installed.items() if output and archive.startswith(output + '.tar.')]
        if len(matches) != 1: raise RuntimeError('Cannot identify Cygwin owner of ' + dll.name + ': ' + output)
        packages.add(matches[0])
    manifest = []
    for name in sorted(packages):
        found = None
        for block in re.split(r'(?m)^\[(?:prev|test|curr)\]\s*$', sections[name]):
            binary = re.search(r'(?m)^install: (\S+)', block)
            source = re.search(r'(?m)^source: (\S+) (\d+) ([0-9a-f]+)', block)
            if binary and Path(binary[1]).name == installed[name] and source:
                found = source; break
        if found is None: raise RuntimeError('Matching sources are unavailable for ' + installed[name])
        url, size, expected = found.groups()
        dest = sources / Path(url).name
        if not dest.exists():
            with urllib.request.urlopen(MIRROR + url, timeout=90) as response, dest.open('wb') as stream:
                shutil.copyfileobj(response, stream)
        digest = hashlib.sha512(dest.read_bytes()).hexdigest()
        if digest != expected or dest.stat().st_size != int(size): raise RuntimeError('Source checksum mismatch: ' + url)
        manifest.append({'package': name, 'installed_archive': installed[name], 'source': MIRROR + url, 'sha512': digest})
    (sources / 'cygwin-runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for path in (ROOT / 'windows').glob('*'):
        if path.is_file() and path.suffix in ('.py', '.sh', '.md'): shutil.copy2(path, sources / path.name)
    version = (ROOT / 'VERSION').read_text().strip()
    with tarfile.open(ROOT / 'dist' / 'windows' / f'TSMA-Kit-{version}-windows-runtime-sources.tar.gz', 'w:gz', compresslevel=1) as archive:
        archive.add(sources, arcname='windows-runtime-sources')
    print(f'Collected sources for {len(manifest)} runtime packages.')


if __name__ == '__main__': main()
