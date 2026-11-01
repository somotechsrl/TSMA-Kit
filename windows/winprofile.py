"""Import only public musical settings; leave existing Windows licenses alone."""
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def install(source, identifier):
    target = Path(os.environ['APPDATA']) / 'Gadwin'
    config = target / 'ToneLib GFX' / '_app.cfg'
    # Never overwrite a user's existing ToneLib setup without their review.
    if config.exists(): return False
    for name in ('ToneLib GFX', 'Shared'):
        for path in (source / 'config' / 'Gadwin' / name).rglob('*'):
            if not path.is_file() or path.suffix == '.reginfo': continue
            dest = target / path.relative_to(source / 'config' / 'Gadwin')
            if dest.exists(): continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    tree = ET.parse(config)
    for value in tree.findall('VALUE'):
        if value.get('name') == 'audio.device.state':
            for child in list(value): value.remove(child)
            setup = ET.SubElement(value, 'DEVICESETUP', deviceType='ASIO',
                                  audioInputDeviceName='JackRouter', audioOutputDeviceName='JackRouter',
                                  audioDeviceRate='48000.0', audioDeviceBufferSize='256')
            if identifier: ET.SubElement(setup, 'MIDIINPUT', name='TSMA ToneLib', identifier=identifier)
        elif value.get('name', '').startswith('recent_') or value.get('name') == 'gfx.impulses.dir':
            value.set('val', '')
        elif value.get('name') == 'gfx.curr.preset': value.set('val', '0')
    tree.write(config, encoding='utf-8', xml_declaration=True)
    return True
