"""Build a single-file TermDash executable with PyInstaller."""

import subprocess
import sys


def main():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "termdash",
        "--console",
        # Collect Textual's bundled CSS and data files
        "--collect-data", "textual",
        # Hidden imports that PyInstaller misses
        "--hidden-import", "textual.widgets",
        "--hidden-import", "textual.css",
        "--hidden-import", "termdash.platform.windows",
        "--hidden-import", "termdash.platform.macos",
        "--hidden-import", "termdash.platform.linux",
        "--hidden-import", "termdash.widgets",
        "--hidden-import", "termdash.analyzer",
        # Entry point
        "termdash/__main__.py",
    ]
    print(f"Running: {' '.join(cmd)}")
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
