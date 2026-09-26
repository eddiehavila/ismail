"""CLI: python -m ismail -p <project> <op> [json-args | @file.json | key=value ...]

  python -m ismail ops                       list ops
  python -m ismail help <op>                 op signature + description
  python -m ismail -p song notes_read '{"track": "bass", "bars": [1, 4]}'
  python -m ismail -p song render bars=[1,8] stems=true
  python -m ismail -p song batch @edits.json      (file holds {"ops": [...]} or a bare list)
"""
import inspect
import json
import os
import sys

from .api import OPS, OpError


def parse_args(args):
    if not args:
        return {}
    if len(args) == 1 and args[0].startswith('@'):
        with open(args[0][1:], encoding='utf8') as f:
            v = json.load(f)
        return {'ops': v} if isinstance(v, list) else v
    if len(args) == 1 and args[0].lstrip().startswith('{'):
        return json.loads(args[0])
    kw = {}
    for a in args:
        k, _, v = a.partition('=')
        try:
            kw[k] = json.loads(v)
        except json.JSONDecodeError:
            kw[k] = v
    return kw


def main(argv):
    project = os.environ.get('ISMAIL_PROJECT', '.')
    if len(argv) >= 2 and argv[0] == '-p':
        project, argv = argv[1], argv[2:]
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    if argv[0] == 'ops':
        for name, fn in OPS.items():
            print(f"{name:<18} {(fn.__doc__ or '').strip().splitlines()[0]}")
        return 0
    if argv[0] == 'help':
        fn = OPS[argv[1]]
        print(f"{argv[1]}{inspect.signature(fn)}\n{inspect.getdoc(fn)}")
        return 0
    name = argv[0]
    kw = parse_args(argv[1:])
    if name not in OPS:
        print(f"ERROR unknown op {name!r}; run 'python -m ismail ops'", file=sys.stderr)
        return 2
    project = kw.pop('project', project)
    try:
        print(OPS[name](project, **kw))
        return 0
    except (OpError, ValueError) as e:  # analysis/instrument/fx errors are ValueErrors with guidance
        print(f"ERROR {e}", file=sys.stderr)
        return 1
    except TypeError as e:
        print(f"ERROR bad arguments for {name}: {e}\n{name}{inspect.signature(OPS[name])}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
