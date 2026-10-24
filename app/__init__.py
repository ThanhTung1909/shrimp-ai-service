"""AquaSense AI Service Application Package"""

import sys
from pathlib import Path

# Thêm packages cục bộ vào sys.path nếu có
_packages_dir = Path(__file__).resolve().parent.parent / "packages"
if _packages_dir.exists() and str(_packages_dir) not in sys.path:
    sys.path.append(str(_packages_dir))

__version__ = "1.0.0"
