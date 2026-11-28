"""
Configuration file for Pytest.
Ensures local packages directory is included in sys.path.
"""

import os
import sys
from pathlib import Path

# Thêm thư mục packages cục bộ vào sys.path nếu có
current_dir = Path(__file__).resolve().parent.parent

# All pytest HTTP clients run in an explicit in-process mode that cannot reach
# the configured Redis, RabbitMQ, or database services. Production defaults are
# not changed because this exists only in the pytest process environment.
os.environ["AQUASENSE_HTTP_TEST_MODE"] = "true"
packages_dir = current_dir / "packages"

if packages_dir.exists() and str(packages_dir) not in sys.path:
    sys.path.insert(0, str(packages_dir))

# Đảm bảo root dir của ai_service có trong sys.path
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))
