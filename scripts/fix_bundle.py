"""Avoid shadowing Windows ICU with a version-suffixed build-runtime ICU.

Some embedded Python distributions ship an unrelated icuuc.dll. PyInstaller
finds it on PATH when resolving Qt6Core, even though Qt uses Windows' unversioned
ICU API. Leave the native Windows DLL resolution intact in that case.
"""
from pathlib import Path
import pefile

root=(Path(__file__).resolve().parents[1]/'dist/LocalCaptions/_internal').resolve()
candidate=root/'icuuc.dll'
if candidate.exists():
    pe=pefile.PE(str(candidate))
    exports={e.name for e in pe.DIRECTORY_ENTRY_EXPORT.symbols}
    pe.close()
    if b'ucnv_open' not in exports:
        system=Path('C:/Windows/System32/icuuc.dll')
        native=pefile.PE(str(system))
        assert b'ucnv_open' in {e.name for e in native.DIRECTORY_ENTRY_EXPORT.symbols}
        native.close()
        candidate.unlink()
        unused=root/'icudt78.dll'
        if unused.exists(): unused.unlink()
        print('Removed conflicting development-runtime ICU; Qt will use Windows system ICU.')
