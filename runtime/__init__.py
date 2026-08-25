"""运行系统路径与本地生产候选配置。"""

from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository

__all__ = ["RuntimePaths", "SystemRepository", "get_runtime_paths"]
