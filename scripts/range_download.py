"""Development helper: resumable range downloads with strict range validation."""
import concurrent.futures
import urllib.request
import time
from pathlib import Path
import sys
import os


def download(url, destination, size):
    destination=Path(destination)
    parts=destination.with_suffix('.parts')
    parts.mkdir(parents=True,exist_ok=True)
    chunk=2*1024*1024
    def fetch(start):
        end=min(size-1,start+chunk-1)
        path=parts/str(start)
        if path.exists() and path.stat().st_size==end-start+1: return path
        for attempt in range(4):
            try:
                request=urllib.request.Request(url+('&' if '?' in url else '?')+f'part={start}',headers={'Range':f'bytes={start}-{end}', 'User-Agent':'LocalCaptions/0.1 (model download)'})
                with urllib.request.urlopen(request,timeout=45) as response:
                    if response.headers.get('Content-Range')!=f'bytes {start}-{end}/{size}':
                        raise RuntimeError('Server did not return the requested range')
                    data=response.read()
                if len(data)!=end-start+1: raise RuntimeError('Incomplete range')
                path.write_bytes(data)
                print(f'{start+len(data)}/{size}',flush=True)
                return path
            except Exception:
                if attempt==3: raise
                time.sleep(1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(os.environ.get('LOCALCAPTIONS_DOWNLOAD_WORKERS','12'))) as pool:
        paths=list(pool.map(fetch,range(0,size,chunk)))
    with destination.open('wb') as out:
        for path in paths: out.write(path.read_bytes())


if __name__=='__main__': download(sys.argv[1],sys.argv[2],int(sys.argv[3]))
