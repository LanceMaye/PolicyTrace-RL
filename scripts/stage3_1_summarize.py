import argparse
import json
from policytrace.stage3_1.summary import summarize
if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True)
    print(json.dumps(summarize(parser.parse_args().run_dir),indent=2))
