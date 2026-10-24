"""
Configuration file for Pytest.
Ensures local packages directory is included in sys.path.
"""

import sys
from pathlib import Path

# Thêm thư mục packages cục bộ vào sys.path nếu có
current_dir = Path(__file__).resolve().parent.parent
packages_dir = current_dir / "packages"

if packages_dir.exists() and str(packages_dir) not in sys.path:
    sys.path.insert(0, str(packages_dir))

# Đảm bảo root dir của ai_service có trong sys.path
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))
