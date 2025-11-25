# --- browser_utils/operations_modules/errors.py ---
import logging
from typing import Optional
from playwright.async_api import Page as AsyncPage, Error as PlaywrightAsyncError

from config import ERROR_TOAST_SELECTOR

logger = logging.getLogger("AIStudioProxyServer")

async def detect_and_extract_page_error(page: AsyncPage, req_id: str) -> Optional[str]:
    """检测并提取页面错误"""
    error_toast_locator = page.locator(ERROR_TOAST_SELECTOR).last
    try:
        await error_toast_locator.wait_for(state='visible', timeout=500)
        message_locator = error_toast_locator.locator('span.content-text')
        error_message = await message_locator.text_content(timeout=500)
        if error_message:
             logger.error(f"[{req_id}]    检测到并提取错误消息: {error_message}")
             return error_message.strip()
        else:
             logger.warning(f"[{req_id}]    检测到错误提示框，但无法提取消息。")
             return "检测到错误提示框，但无法提取特定消息。"
    except PlaywrightAsyncError: 
        return None
    except Exception as e:
        logger.warning(f"[{req_id}]    检查页面错误时出错: {e}")
        return None

async def save_error_snapshot(error_name: str = 'error'):
    """
    保存错误快照 (Legacy wrapper).

    DEPRECATED: This function now uses the new comprehensive snapshot system.
    For new code, use save_comprehensive_snapshot() from debug_utils directly.

    This wrapper maintains backward compatibility while leveraging the enhanced
    debugging capabilities.
    """
    from browser_utils.debug_utils import save_error_snapshot_legacy
    await save_error_snapshot_legacy(error_name)