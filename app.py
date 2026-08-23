"""Compatibility launcher for the Jaza Sentinel local server.

The canonical entrypoint remains ``main.py``.  This shim preserves the common
``python app.py`` command used by the existing local workflow.
"""

from main import main


if __name__ == "__main__":
    main()
