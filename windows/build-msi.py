#!/usr/bin/env python3
"""Freeze the native GUI and generate a real x64 WiX v3 MSI, with shortcuts."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'dist' / 'windows'
VERSION = (ROOT / 'VERSION').read_text().strip()
WIX = 'http://schemas.microsoft.com/wix/2006/wi'
ET.register_namespace('', WIX)


def node(parent, tag, **attrs):
    return ET.SubElement(parent, '{' + WIX + '}' + tag, attrs)


def main():
    os.chdir(ROOT)
    if not (OUT / 'engine' / 'sooperlooper.exe').is_file(): raise SystemExit('Build the Cygwin engine first.')
    licenses = OUT / 'licenses'; licenses.mkdir(exist_ok=True)
    shutil.copy2(OUT / 'SOOPERLOOPER-COPYING.txt', licenses / 'SooperLooper.txt')
    for path in [Path(sys.base_prefix) / 'LICENSE.txt', *Path(sys.base_prefix).glob('tcl/*/license.terms')]:
        if path.exists(): shutil.copy2(path, licenses / (path.parent.name + '-' + path.name))
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
            '--name', 'TSMA-Kit', '--icon', 'windows/tsma-kit.ico', '--distpath', str(OUT / 'app'),
            '--workpath', '.cache-build/windows/pyinstaller', '--specpath', '.cache-build/windows',
            '--paths', 'windows', '--paths', 'bin', '--hidden-import', 'winmidi', '--hidden-import', 'winjack',
            '--add-data', str(OUT / 'engine') + os.pathsep + 'engine',
            '--add-data', 'config/Gadwin' + os.pathsep + 'config/Gadwin',
            '--add-data', 'windows/tsma-kit.ico' + os.pathsep + '.',
            '--add-data', str(licenses) + os.pathsep + 'licenses', 'windows/app.py']
    subprocess.run(args, check=True)
    app = OUT / 'app' / 'TSMA-Kit'
    subprocess.run([str(app / 'TSMA-Kit.exe'), '--self-test'], check=True, timeout=30)
    root = ET.Element('{' + WIX + '}Wix')
    product = node(root, 'Product', Id='*', Name='TSMA Kit (Windows preview)', Language='1033',
                   Version=VERSION, Manufacturer='Somotech', UpgradeCode='06D20391-E65C-4D7D-92B8-FBFFEBB60FB8')
    node(product, 'Package', InstallerVersion='500', Compressed='yes', InstallScope='perMachine', Platform='x64')
    node(product, 'MajorUpgrade', DowngradeErrorMessage='A newer TSMA Kit is installed.')
    node(product, 'MediaTemplate', EmbedCab='yes')
    condition = node(product, 'Condition', Message='TSMA Kit requires Windows 10 or 11, 64-bit.')
    condition.text = 'Installed OR (VersionNT64 AND WINDOWSBUILD >= 10240)'
    build = node(product, 'Property', Id='WINDOWSBUILD')
    node(build, 'RegistrySearch', Id='WindowsBuildNumber', Root='HKLM',
         Key='SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion', Name='CurrentBuildNumber', Type='raw', Win64='yes')
    node(product, 'Icon', Id='AppIcon', SourceFile=str(ROOT / 'windows/tsma-kit.ico'))
    node(product, 'Property', Id='ARPPRODUCTICON', Value='AppIcon')
    node(product, 'Property', Id='ARPHELPLINK', Value='https://github.com/somotechsrl/TSMA-Kit')
    directory = node(product, 'Directory', Id='TARGETDIR', Name='SourceDir')
    program = node(directory, 'Directory', Id='ProgramFiles64Folder')
    install = node(program, 'Directory', Id='INSTALLDIR', Name='TSMA Kit')
    menu = node(directory, 'Directory', Id='ProgramMenuFolder')
    node(menu, 'Directory', Id='AppMenu', Name='TSMA Kit')
    node(directory, 'Directory', Id='DesktopFolder')
    feature = node(product, 'Feature', Id='Complete', Title='TSMA Kit', Level='1')
    dirs = {Path('.'): install}
    for path in sorted(app.rglob('*')):
        rel = path.relative_to(app)
        ident = 'P' + hashlib.sha1(rel.as_posix().encode()).hexdigest()
        if path.is_dir():
            dirs[rel] = node(dirs[rel.parent], 'Directory', Id=ident, Name=path.name); continue
        component = node(dirs[rel.parent], 'Component', Id='C' + ident, Win64='yes',
                         Guid=str(uuid.uuid5(uuid.NAMESPACE_URL, 'https://github.com/somotechsrl/TSMA-Kit/windows/' + rel.as_posix())))
        file = node(component, 'File', Id='F' + ident, Name=path.name, Source=str(path), KeyPath='yes')
        if rel == Path('TSMA-Kit.exe'):
            for where in ('AppMenu', 'DesktopFolder'):
                node(file, 'Shortcut', Id=where + 'Shortcut', Directory=where, Name='TSMA Kit',
                     Advertise='yes', Icon='AppIcon', WorkingDirectory='INSTALLDIR')
            node(component, 'RemoveFolder', Id='RemoveAppMenu', Directory='AppMenu', On='uninstall')
        node(feature, 'ComponentRef', Id='C' + ident)
    source = OUT / 'TSMA-Kit.wxs'
    ET.ElementTree(root).write(source, encoding='utf-8', xml_declaration=True)
    wixbase = Path(os.environ.get('WIX', 'C:/Program Files (x86)/WiX Toolset v3.14')) / 'bin'
    candle = shutil.which('candle.exe') or str(wixbase / 'candle.exe')
    light = shutil.which('light.exe') or str(wixbase / 'light.exe')
    subprocess.run([candle, '-nologo', '-arch', 'x64', '-out', str(OUT / 'TSMA-Kit.wixobj'), str(source)], check=True)
    subprocess.run([light, '-nologo', '-sval', '-out', str(OUT / f'TSMA-Kit-{VERSION}-windows-preview-x64.msi'),
                    str(OUT / 'TSMA-Kit.wixobj')], check=True)


if __name__ == '__main__': main()
