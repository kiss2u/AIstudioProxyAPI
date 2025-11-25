# --- browser_utils/initialization/__init__.py ---
from .core import (
    initialize_page_logic as _initialize_page_logic,
    close_page_logic as _close_page_logic,
    signal_camoufox_shutdown,
    enable_temporary_chat_mode
)

__all__ = [
    '_initialize_page_logic',
    '_close_page_logic',
    'signal_camoufox_shutdown',
    'enable_temporary_chat_mode'
]