import os
import sys
import logging
import logging.handlers
from launcher.config import LOG_DIR, LAUNCHER_LOG_FILE_PATH

logger = logging.getLogger("CamoufoxLauncher")

def setup_launcher_logging(log_level=logging.INFO):
    os.makedirs(LOG_DIR, exist_ok=True)
    file_log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s:%(funcName)s:%(lineno)d] - %(message)s')
    console_log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.setLevel(log_level)
    logger.propagate = False
    if os.path.exists(LAUNCHER_LOG_FILE_PATH):
        try:
            os.remove(LAUNCHER_LOG_FILE_PATH)
        except OSError:
            pass
    file_handler = logging.handlers.RotatingFileHandler(
        LAUNCHER_LOG_FILE_PATH, maxBytes=2*1024*1024, backupCount=3, encoding='utf-8', mode='w'
    )
    file_handler.setFormatter(file_log_formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(console_log_formatter)
    logger.addHandler(stream_handler)
    logger.info("=" * 30 + " Camoufox启动器日志系统已初始化 " + "=" * 30)
    logger.info(f"日志级别设置为: {logging.getLevelName(logger.getEffectiveLevel())}")
    logger.info(f"日志文件路径: {LAUNCHER_LOG_FILE_PATH}")