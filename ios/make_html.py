"""Copies the controller page out of server.py so the app and the PC server always match."""
import re
from pathlib import Path

here = Path(__file__).resolve().parent
src = (here.parent / "server.py").read_text(encoding="utf-8")
page = re.search(r'PAGE = r"""(.*?)"""', src, re.S).group(1)
(here / "PhonePad" / "controller.html").write_text(page, encoding="utf-8")
print("controller.html written,", len(page), "chars")
