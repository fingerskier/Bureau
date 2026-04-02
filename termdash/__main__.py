"""Entry point for `python -m termdash`."""

try:
    from .app import TermDashApp
except ImportError:
    from termdash.app import TermDashApp


def main():
    app = TermDashApp()
    app.run()


if __name__ == "__main__":
    main()
