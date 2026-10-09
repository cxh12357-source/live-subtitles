"""Ship the installed distributions' license/notice files with the executable."""
from importlib.metadata import distributions
from pathlib import Path
import shutil

root=Path(__file__).resolve().parents[1]
destination=root/'dist/LocalCaptions/third-party-licenses'
destination.mkdir(parents=True,exist_ok=True)
for distribution in distributions():
    name=distribution.metadata.get('Name','unknown')
    for item in distribution.files or []:
        label=str(item).lower()
        if any(part in ('licenses','license','licences') for part in item.parts) or any(token in item.name.lower() for token in ('license','copying','notice')):
            source=Path(distribution.locate_file(item))
            if source.is_file():
                target=destination/name/str(item).replace('../','').replace('..\\','')
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
for name in ('README.md','LANGUAGES.md','TEST_RESULTS.md','TEST_RESULTS_INITIAL.md','LATENCY_RESULTS.md','SPEED_RESULTS.md','THIRD_PARTY.md','LICENSE'):
    if (root/name).exists(): shutil.copy2(root/name,destination.parent/name)
print(destination)
