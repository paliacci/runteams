"""Start the account-free local asset service: python -m runteams_core.application.community."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading

from runteams_core.application.local_application import LocalApplication
from runteams_core.application.http.local_http import LocalServer


def default_data_directory():
    if os.environ.get('RUNTEAMS_DATA'):
        return Path(os.environ['RUNTEAMS_DATA']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/RunTeams.ai/community'
    if os.name == 'nt':
        base = os.environ.get('APPDATA') or os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Roaming'
        return Path(base) / 'RunTeams.ai/community'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'runteams/community'


def _port(value):
    number = int(value)
    if not 0 <= number <= 65535:
        raise argparse.ArgumentTypeError('端口必须在0到65535之间。')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=default_data_directory())
    parser.add_argument('--port', type=_port)
    presentation = parser.add_mutually_exclusive_group()
    presentation.add_argument('--open', action='store_true', help='在浏览器中打开本机资产界面')
    presentation.add_argument('--desktop', action='store_true', help='启动独立原生本机壳')
    parser.add_argument('--desktop-host', type=Path, help='明确指定已构建的本机版.app')
    parser.add_argument('--owner-stdin', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.desktop_host and not args.desktop:
        parser.error('--desktop-host 只与 --desktop 一起使用')
    if args.owner_stdin and (args.desktop or args.open):
        parser.error('原生服务的所有者通道不能与界面启动选项混用')
    if args.desktop:
        from runteams_core.application.community_native import launch
        try: return launch(args.data_dir, args.port if args.port is not None else 0, args.desktop_host)
        except (OSError, ValueError) as error: parser.exit(2, str(error) + '\n')
    # One process opens exactly one library; bind host/runtime paths before imports.
    os.environ['RUNTEAMS_DATA'] = str(args.data_dir.expanduser().resolve())
    port = args.port if args.port is not None else (0 if args.owner_stdin else 8792)
    try:
        application = LocalApplication(args.data_dir)
        server = LocalServer(application, port)
    except (OSError, ValueError) as error:
        parser.exit(2, '无法打开本机资料库或监听端口：' + str(error) + '\n')

    def stop(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        with server:
            if args.owner_stdin:
                # Only this service's owner pipe is watched. Never discover,
                # adopt or stop a process by a shared port or PID file.
                server.daemon_threads = False
                def owner_closed():
                    while sys.stdin.buffer.read(1):
                        pass
                    server.shutdown()
                threading.Thread(target=owner_closed, daemon=True).start()
            print(json.dumps(server.descriptor(native=args.owner_stdin), ensure_ascii=False), flush=True)
            if args.open:
                import webbrowser
                webbrowser.open(server.origin + '/')
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    raise SystemExit(main())
