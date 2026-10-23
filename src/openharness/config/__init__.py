"""配置层：`.oh/` 路径解析与 settings 加载。"""

from .paths import DEFAULT_OH_DIRNAME, ensure_oh_dir, oh_dir, oh_path
from .settings import default_config, load_config, save_permissions

__all__ = [
    "DEFAULT_OH_DIRNAME", "ensure_oh_dir", "oh_dir", "oh_path",
    "default_config", "load_config", "save_permissions",
]
