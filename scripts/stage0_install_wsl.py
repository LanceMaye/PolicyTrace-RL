"""Install the WSL platform only; never install a distribution or restart Windows."""
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import winreg

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/stage0/wsl_install.json'


def save(status: str, steps: list[dict]) -> None:
    REPORT.write_text(json.dumps({'status':status,'distribution':None,
        'installation_scope':'WSL platform only; distribution installation deferred by user',
        'timestamp_utc':datetime.now(timezone.utc).isoformat(), 'automatic_restart':False,
        'steps':steps},indent=2,ensure_ascii=False),encoding='utf-8')


def run(args: list[str]) -> dict:
    proc = subprocess.run(['wsl.exe',*args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=1200)
    data = proc.stdout
    # wsl emits UTF-16 even when Chinese text has few NUL bytes. DISM can mix
    # console encoding and UTF-16; preserve the original bytes for diagnosis.
    (ROOT/'reports/stage0'/('wsl-'+args[0].lstrip('-')+'-raw.bin')).write_bytes(data)
    text = data.decode('utf-16-le',errors='replace') if b'\0' in data else data.decode('gb18030',errors='replace')
    return {'command':['wsl.exe',*args],'exit_code':proc.returncode,'output':text}


def reboot_pending() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'):
            return True
    except FileNotFoundError:
        return False


def main() -> None:
    steps = []
    if not ctypes.windll.shell32.IsUserAnAdmin():
        save('BLOCKED_ADMIN_REQUIRED',steps)
        raise SystemExit(1)
    save('RUNNING',steps)
    try:
        platform = run(['--install','--no-distribution'])
        steps.append(platform)
        save('RUNNING',steps)
        if platform['exit_code'] not in (0,3010):
            save('FAIL_PLATFORM_INSTALL',steps)
            return
        # Enabling Windows components can require a restart. Do not initiate it.
        if reboot_pending() or platform['exit_code']==3010 or '重启' in platform['output'] or '重新启动' in platform['output'] or 'restart' in platform['output'].lower() or 'reboot' in platform['output'].lower():
            save('REBOOT_REQUIRED',steps)
            return
        steps.append(run(['--version']))
        save('WSL_CORE_INSTALLED',steps)
    except Exception as exc:
        steps.append({'exception_type':type(exc).__name__})
        save('FAIL',steps)


if __name__=='__main__':
    main()
