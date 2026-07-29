"""
日志系统模块
全局 logger，记录服务器运行状态。
对话记录由 Redis checkpoint 持久化，日志不重复记录。
"""
import logging
import os


# ==========================================
# 常量定义
# ==========================================
LOG_DIR = "logs"


# ==========================================
# 设置全局 logger
# ==========================================
def setup_global_logger(
    log_to_file: bool = True,
    log_to_console: bool = True,
    level: int = logging.DEBUG,
    clear_previous_logs: bool = False,
) -> logging.Logger:
    """
    全局 logger，同时输出到终端 (INFO) 和文件 (DEBUG)。

    Args:
        log_to_file: 是否输出到文件 (bool)，默认 True
        log_to_console: 是否输出到终端 (bool)，默认 True
        level: logger 级别 (int)，默认 DEBUG
        clear_previous_logs: 是否清空之前的日志文件 (bool)，默认 False

    Returns:
        logging.Logger: 配置好的 logger
    """
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    if clear_previous_logs:
        clear_log_files()

    logger = logging.getLogger("global_logger")

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 终端 handler: INFO 级别
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 文件 handler: DEBUG 级别
    if log_to_file:
        log_file = os.path.join(LOG_DIR, "global.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# ==========================================
# 清空日志文件
# ==========================================
def clear_log_files():
    """
    清空 logs 目录下所有 .log 文件。
    在应用启动时调用，确保每次运行都是新的日志。
    """
    if not os.path.exists(LOG_DIR):
        return
    for filename in os.listdir(LOG_DIR):
        if filename.endswith(".log"):
            log_file = os.path.join(LOG_DIR, filename)
            try:
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write("")
            except Exception as e:
                print(f"[WARNING] 清空日志文件失败 {filename}: {e}")
