"""Reject product-specific host implementations in public source and wheels.

This checks every maintained UI file, including files not selected by the HTTP
manifest. Portable asset formats and model-vendor integrations are public core
contracts; they are intentionally distinct from product-account presentation.
"""
import argparse
import json
from pathlib import Path
import re
import zipfile


UI_SUFFIXES = {'.js', '.mjs', '.cjs', '.css', '.html', '.json'}
EXCLUDED = {'node_modules', '__pycache__', '.git'}
RULES = {
    'private-host-symbol': re.compile(
        r'\b(?:RunTeamsOfficial\w*|RunTeamsProduct\w*|RunTeamsAccountShell|'
        r'RunTeamsNativeAssets|RunTeamsDesktopLogin|RunTeamsSupport|RunTeamsSidebarViews|'
        r'accountNotifyNativeReady|accountOpenWorkNotification)\b'),
    'private-host-path': re.compile(r'/official-ui/|runteams_official[/.]'),
    'product-account-access': re.compile(
        r'\b(?:S|state)\.account\??\.(?:signed_in|user_id|auth_issuer|device_data_scope|entitlements)\b|'
        r'\bS\.activeOrganization\b'),
    'commercial-implementation': re.compile(
        r'\b(?:function\s+)?(?:account(?:Logout|StartSubscription|Subscription\w*|Wallet\w*|Team\w*)|'
        r'subscription(?:Plans|Price|Action|Comparison|Pending)|marketplace(?:Hero|Card|DetailPage))\s*\('),
    'commercial-route': re.compile(r'''["'`](/(?:api/)?(?:billing|wallet|marketplace|subscriptions)(?:[/"'`?]))'''),
    'edition-switch': re.compile(r'runteams-edition|RunTeamsApplication\?*\.edition'),
}


def inspect_ui(name, text):
    """Report structural ownership markers without publishing source excerpts."""
    findings = []
    for rule, pattern in RULES.items():
        for match in pattern.finditer(text):
            findings.append({'path': name, 'line': text.count('\n', 0, match.start()) + 1, 'rule': rule})
    return findings


def source_files(root):
    root = Path(root)
    for folder in ('web', 'frontend/community'):
        for path in sorted((root / folder).rglob('*')):
            if (path.is_file() and path.suffix in UI_SUFFIXES
                    and not EXCLUDED.intersection(path.relative_to(root).parts)):
                if path.is_symlink():
                    raise ValueError('Linked public UI input: ' + str(path.relative_to(root)))
                yield path.relative_to(root).as_posix(), path.read_text()


def check(root):
    root = Path(root)
    findings = []
    count = 0
    for name, text in source_files(root):
        count += 1
        findings.extend(inspect_ui(name, text))
    contract = json.loads((root / 'contracts/page-routes.json').read_text())
    for row in contract['routes']:
        findings.extend(inspect_ui('contracts/page-routes.json', json.dumps(row)))
    # Check every literal static import in the shared entry, including files that
    # would otherwise be stripped or silently omitted during local composition.
    html = (root / 'web/index.html').read_text()
    asset_map = json.loads((root / 'runteams_core/application/http/community_web_assets.json').read_text())
    for tag in re.findall(r'<(?:script|link)\b[^>]*>', html):
        for url in re.findall(r'(?:src|href)="(/[^"?#]+)', tag):
            if url not in asset_map:
                findings.append({'path': 'web/index.html', 'rule': 'unregistered-static-input', 'url': url})
    if findings:
        raise ValueError(json.dumps(findings, ensure_ascii=False))
    return {'ui_sources': count, 'private_implementation_findings': 0,
            'all_ui_files_scanned': True, 'static_inputs_registered': True}


def check_wheel(wheel):
    findings = []
    count = 0
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            name = info.filename
            if {'runteams_official', 'official-ui'}.intersection(Path(name).parts):
                findings.append({'path': name, 'rule': 'private-package-input'})
            if ('/_resources/web/' in name or '/_resources/frontend/community/' in name):
                if Path(name).suffix in UI_SUFFIXES:
                    count += 1
                    findings.extend(inspect_ui(name, archive.read(name).decode()))
            if name.endswith('/_resources/contracts/page-routes.json'):
                for row in json.loads(archive.read(name))['routes']:
                    findings.extend(inspect_ui(name, json.dumps(row)))
    if findings:
        raise ValueError(json.dumps(findings, ensure_ascii=False))
    if not count:
        raise ValueError('The wheel contains no shared UI payload.')
    return {'wheel_ui_sources': count, 'private_implementation_findings': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--wheel', type=Path)
    args = parser.parse_args()
    if args.wheel:
        result = check_wheel(args.wheel)
    else:
        from .source_root import root
        result = check(args.root or root())
    print(json.dumps(result))


if __name__ == '__main__':
    main()
