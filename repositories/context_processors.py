from pathlib import Path

STYLESHEET = Path(__file__).resolve().parent / 'static' / 'repositories' / 'repositories.css'


def stylesheet_version():
    """Return a value that changes whenever the repositories stylesheet changes.

    The stylesheet is served with a long browser cache lifetime, so an edited
    rule would otherwise keep showing the old version until the user hard
    refreshes the page.
    """
    try:
        return int(STYLESHEET.stat().st_mtime)
    except OSError:
        return 0


def repository_assets(request):
    return {'repositories_css_version': stylesheet_version()}
