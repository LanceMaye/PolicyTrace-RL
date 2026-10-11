"""No fetch/install: verify existing Fork; --apply installs only the approved policy."""
import argparse
import json
from policytrace.policy import install_policy_patch,verify_fork
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(install_policy_patch() if args.apply else verify_fork(),indent=2))
