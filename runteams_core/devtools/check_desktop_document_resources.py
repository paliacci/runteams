"""Reject stale desktop candidates that still carry the retired editor kernel."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
from pathlib import Path


def verify(app):
    app=Path(app)
    resource=app/'Contents/Resources/server/_internal/siyuan'
    if resource.exists() or resource.is_symlink():
        raise ValueError('应用仍含已退役的文档内核，请从当前源码重新构建。')
    return True


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',required=True,type=Path)
    verify(parser.parse_args().app)
