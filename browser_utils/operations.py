# --- browser_utils/operations.py ---
# 浏览器页面操作相关功能模块
# Refactored into browser_utils/operations_modules/

from .operations_modules.parsers import (
    _parse_userscript_models,
    _get_injected_models,
    _handle_model_list_response
)
from .operations_modules.interactions import (
    get_raw_text_content,
    get_response_via_edit_button,
    get_response_via_copy_button,
    _wait_for_response_completion,
    _get_final_response_content
)
from .operations_modules.errors import (
    detect_and_extract_page_error,
    save_error_snapshot
)
