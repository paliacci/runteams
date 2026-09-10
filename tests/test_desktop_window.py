import unittest
from pathlib import Path


class DesktopWindowTests(unittest.TestCase):
    def test_native_webkit_window_uses_transparent_full_size_titlebar(self):
        root = Path(__file__).parents[1]
        host = (root / "desktop" / "window_host.swift").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")

        self.assertIn("import WebKit", host)
        self.assertIn(".fullSizeContentView", host)
        self.assertIn("window.titleVisibility = .hidden", host)
        self.assertIn("window.titlebarAppearsTransparent = true", host)
        self.assertIn("window.titlebarSeparatorStyle = .none", host)
        self.assertIn("runteams-native-macos", host)
        self.assertIn("class WindowDragView", host)
        self.assertIn("window?.performDrag(with: event)", host)
        self.assertIn("final class HeaderDragRegionView: WindowDragView", host)
        self.assertIn("WKScriptMessageHandler", host)
        self.assertIn('name: "runteamsWindowDragRegions"', host)
        self.assertIn("document.querySelector('.vhead')", host)
        self.assertIn("header.querySelectorAll('button,input,a,select,textarea,[role=\"button\"],[onclick]')", host)
        self.assertIn("headerDragView.updateRegions(from: message.body)", host)
        self.assertIn(".runteams-native-macos .rail{padding-top:36px}", styles)
        self.assertIn(".runteams-native-macos .body.rail-collapsed .vhead{padding-left:236px}", styles)

    def test_build_prefers_native_window_and_keeps_browser_fallback(self):
        root = Path(__file__).parents[1]
        build = (root / "desktop" / "build.sh").read_text(encoding="utf-8")

        self.assertIn('xcrun swiftc "$ROOT/desktop/window_host.swift"', build)
        self.assertIn("-framework AppKit -framework WebKit", build)
        self.assertIn('WINDOW_HOST="${HERE}/RunTeamsWindow.app/Contents/MacOS/RunTeamsWindow"', build)
        self.assertLess(build.index('if [ -x "$WINDOW_HOST" ]'),
                        build.index('elif [ -d "/Applications/Google Chrome.app" ]'))
        self.assertIn("NSAllowsLocalNetworking", build)


if __name__ == "__main__":
    unittest.main()
