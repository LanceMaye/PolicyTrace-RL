"""Read-only root Git/prospective publication audit. Never stages, commits or pushes."""
import json
import re
import subprocess
from pathlib import Path

from policytrace.data.manifests import ROOT, digest, file_hash, write_json

REPORT_FILES = {'STAGE3_1_LOCAL_PREP_REPORT.md','check_results.json','git_safety_audit.json','environment_check.json',
                'data_inventory.json','cli_checks.json','offline.xml','harness.xml','regression.xml','regression_scope.json'}


def candidates(root=ROOT):
    roots = ('src','scripts','tests','configs','docs','.agents/skills')
    extensions = {'.py','.md','.json','.yaml','.yml','.toml','.txt','.lock','.sh','.ps1','.ini'}
    paths = [p for name in roots for p in (root/name).rglob('*') if p.is_file() and p.suffix in extensions
             and not any(part in ('__pycache__','.pytest_cache','.ruff_cache') or part.endswith('.egg-info') for part in p.parts)
             and not p.name.startswith('.env')]
    paths += [root/name for name in ('.gitignore','.env.example','README.md','pyproject.toml','requirements-stage0.lock','requirements-stage3_1-candidate.txt') if (root/name).is_file()]
    paths += [root/'reports/stage0/data_manifest.json']
    paths += [root/name for name in (
        'reports/stage0/versions.json','reports/stage0/STAGE0_REPORT.md','reports/stage1/STAGE1_REPORT.md',
        'reports/stage2/STAGE2_REPORT.md','reports/stage2/STAGE2_COMPLETION_REPORT.md',
        'reports/stage3_0/STAGE3_0_REPORT.md','reports/policy_transition_v2/POLICY_TRANSITION_REPORT.md')]
    paths += [p for p in (root/'reports/stage3_1').glob('*') if p.name in REPORT_FILES]
    return sorted(set(p.relative_to(root).as_posix() for p in paths if p.is_file()))


def git(root, *args):
    result = subprocess.run(['git','-C',str(root),*args],capture_output=True)
    return result.returncode,result.stdout.decode('utf-8',errors='replace')


def audit(root=ROOT):
    paths = candidates(root)
    forbidden = ('data/raw/','data/private/','data/processed/','data/tokenizers/','data/splits/stage2/','external/')
    violations = [p for p in paths if p.startswith(forbidden) or (p.startswith('.env') and p!='.env.example')
                  or Path(p).suffix in ('.safetensors','.bin','.pem','.key','.pt')]
    findings = []
    # Detect real-looking literal credentials, retaining location/type only, never values.
    patterns = [('private_key',re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')),
                ('provider_key',re.compile(r'\bsk-[A-Za-z0-9_-]{24,}\b')),
                ('github_token',re.compile(r'\b(?:ghp_|github_pat_)[A-Za-z0-9_]{24,}\b'))]
    hashes = {}
    for name in paths:
        p = root/name;hashes[name]=file_hash(p)
        if p.stat().st_size > 3_000_000: continue
        text = p.read_text(encoding='utf-8',errors='replace')
        for kind,pattern in patterns:
            # Fixture concatenations deliberately avoid real-looking complete credentials.
            if pattern.search(text): findings.append({'path':name,'kind':kind})
    is_repo = (root/'.git').exists()
    git_state = {'repository_present':is_repo,'history_audit':'NOT_AVAILABLE_NO_ROOT_GIT',
                 'tracked_files':0,'staged_files':0,'secret_values_read_or_printed':False}
    tracked_violations = []
    if is_repo:
        code, tracked = git(root,'ls-files')
        if code: raise ValueError('Root Git ls-files failed')
        tracked_names = tracked.splitlines()
        tracked_violations = [p for p in tracked_names if p.startswith(forbidden) or (p.startswith('.env') and p!='.env.example')]
        tracked_violations += sorted(set(tracked_names)-set(paths))
        # Never read .env/key files even if tracked. Their path is already a blocker.
        _, staged = git(root,'diff','--cached','--name-only')
        _, status = git(root,'status','--porcelain')
        _, diff_names = git(root,'diff','--name-only')
        code, history_names = git(root,'log','--all','--format=','--name-only')
        history_forbidden = [p for p in set(history_names.splitlines()) if p.startswith(forbidden) or (p.startswith('.env') and p!='.env.example')]
        # Inspect public candidate content in history only; never retrieve known secret/private paths.
        history_findings = []
        if code == 0:
            _, commits = git(root,'rev-list','--all')
            for commit in commits.splitlines():
                for name in paths:
                    code, blob = git(root,'show',f'{commit}:{name}')
                    if code == 0:
                        for kind,pattern in patterns:
                            if pattern.search(blob): history_findings.append({'path':name,'kind':kind,'commit':commit})
        _, ignored = git(root,'check-ignore',*['data/raw/check.json','.env','data/private/check.json','data/processed/check.json','data/tokenizers/check.json','data/splits/stage2/check.json','external/check'])
        git_state.update(history_audit='BLOCKED' if history_forbidden or history_findings else 'PASS',
            history_forbidden_path_count=len(history_forbidden),history_secret_findings=history_findings,
            tracked_files=len(tracked_names),staged_files=len(staged.splitlines()),status_path_count=len(status.splitlines()),
            unstaged_path_count=len(diff_names.splitlines()),check_ignore_matches=len(ignored.splitlines()))
    ignore = (root/'.gitignore').read_text(encoding='utf-8')
    required_ignore = ['.env','external/','data/raw/','data/private/','data/processed/','data/tokenizers/','data/splits/stage2/']
    ignore_missing = [line for line in required_ignore if line not in ignore.splitlines()]
    blockers = violations+tracked_violations+ignore_missing
    status = 'PASS_PROSPECTIVE_PUBLICATION' if not blockers and not findings and git_state['history_audit']!='BLOCKED' else 'BLOCKED_GIT_SAFETY'
    if git_state.get('history_secret_findings') or git_state.get('history_forbidden_path_count'):
        status = 'BLOCKED_SECRET_HISTORY'
    return {'status':status,'git':git_state,'candidate_count':len(paths),'candidate_manifest_sha256':digest(paths),
            'audited_code_content_sha256':digest({n:s for n,s in hashes.items() if not n.startswith('reports/')}),
            'candidate_files':paths,'blocked_paths':blockers,'secret_findings':findings,
            'limitations':['Root Git history cannot be audited before the user initializes it'] if not is_repo else [],
            'mutating_git_commands_executed':0,'ssh_connections':0,'env_file_read':False}


def main():
    result = audit()
    write_json(ROOT/'reports/stage3_1/git_safety_audit.json',result)
    # Exact allowlist is a review artifact; commands are never executed here.
    write_json(ROOT/'data/private/stage3_1/publication_allowlist.json',{'files':result['candidate_files']})
    print(json.dumps({k:result[k] for k in ('status','git','candidate_count','secret_findings','mutating_git_commands_executed')},indent=2))
    return 0 if result['status']=='PASS_PROSPECTIVE_PUBLICATION' else 2


if __name__=='__main__':
    raise SystemExit(main())
