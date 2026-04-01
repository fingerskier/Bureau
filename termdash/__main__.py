"""Entry point for `python -m termdash`."""

from .app import TermDashApp


def main():
    app = TermDashApp()
    app.run()


if __name__ == "__main__":
    main()
