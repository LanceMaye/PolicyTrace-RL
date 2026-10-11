"""Download the official signed Ubuntu 22.04 bundle for installation before reboot."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://wslstorestorage.blob.core.windows.net/wslblob/Ubuntu2204-221101.AppxBundle'
EXPECTED_BYTES = 1116834851
REPORT = ROOT/'reports/stage0/ubuntu_package.json'


def main() -> None:
    folder = ROOT/'external/installers'
    folder.mkdir(parents=True,exist_ok=True)
    target = folder/'Ubuntu2204-221101.AppxBundle'
    part = target.with_suffix(target.suffix+'.part')
    if not target.exists():
        offset = part.stat().st_size if part.exists() else 0
        headers = {'Range':f'bytes={offset}-'} if offset else {}
        with urllib.request.urlopen(urllib.request.Request(URL,headers=headers),timeout=60) as response:
            resumed = offset and response.status==206
            if resumed and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):
                raise ValueError('Unexpected download range')
            downloaded = offset if resumed else 0
            next_progress = downloaded + 100*1024*1024
            with part.open('ab' if resumed else 'wb') as stream:
                while chunk:=response.read(4*1024*1024):
                    stream.write(chunk)
                    downloaded += len(chunk)
                    if downloaded>=next_progress:
                        print(f'Downloaded {downloaded/1024**2:.0f} MiB / {EXPECTED_BYTES/1024**2:.0f} MiB',flush=True)
                        next_progress += 100*1024*1024
        if part.stat().st_size!=EXPECTED_BYTES:
            raise ValueError('Incomplete Ubuntu bundle download')
        part.replace(target)
    if target.stat().st_size!=EXPECTED_BYTES:
        raise ValueError('Unexpected Ubuntu bundle size')
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream,'sha256').hexdigest()
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corrupted Ubuntu bundle ZIP')
        manifest = archive.read('AppxMetadata/AppxBundleManifest.xml').decode('utf-8-sig')
    (folder/'Ubuntu2204-bundle-manifest.xml').write_text(manifest,encoding='utf-8')
    report = {'status':'DOWNLOADED_VERIFIED','source_document':'https://learn.microsoft.com/en-us/windows/wsl/install-manual',
              'official_link':'https://aka.ms/wslubuntu2204','resolved_url':URL,'size_bytes':target.stat().st_size,
              'sha256':digest,'bundle_path':str(target),'integrity':'size + SHA256 recorded + ZIP CRC; Windows Add-AppxPackage validates signing'}
    REPORT.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Official Ubuntu 22.04 bundle ready for Add-AppxPackage.',flush=True)


if __name__=='__main__':
    main()
