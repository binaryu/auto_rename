import contextvars
import itertools
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# 日志格式
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 当前处理文件的日志标识（线程/协程隔离），用于并发处理时区分不同文件的日志
_current_file_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_file_id", default=""
)
_file_seq = itertools.count(1)  # 全局递增序号，区分同一文件的不同处理批次

# 日志级别映射
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _truncate_middle(text: str, max_len: int = 48) -> str:
    """从中间截断长文件名，保留开头（片名）和结尾（画质/扩展名）"""
    if len(text) <= max_len:
        return text
    keep_right = 18
    keep_left = max_len - keep_right - 1  # 减 1 给省略号
    return f"{text[:keep_left]}…{text[-keep_right:]}"


def make_file_id(file_path_or_name: str) -> str:
    """生成文件日志标识，形如 '#12 爱恋.S01E01.1080p.BluRay...'"""
    normalized = str(file_path_or_name).replace("\\", "/")
    name = os.path.basename(normalized) or normalized
    return f"#{next(_file_seq)} {_truncate_middle(name)}"


def set_file_id(file_path_or_name: str) -> None:
    """为当前上下文设置文件日志标识；已设置则不重复分配，保证一次处理只用一个编号"""
    if not _current_file_id.get():
        _current_file_id.set(make_file_id(file_path_or_name))


def clear_file_id() -> None:
    """清除当前上下文的文件日志标识"""
    _current_file_id.set("")


def get_file_id() -> str:
    """获取当前上下文的文件日志标识，无则为空字符串"""
    return _current_file_id.get()


def with_file_id(message: str) -> str:
    """给消息加上当前文件标识前缀（供控制台 print 使用，写入日志的由 Formatter 处理）"""
    file_id = get_file_id()
    if file_id:
        return f"[{file_id}] {message}"
    return message


class TaskIdFilter(logging.Filter):
    """把当前线程/协程的文件标识注入到每条日志记录中"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.file_id = get_file_id()
        return True


class TaskIdFormatter(logging.Formatter):
    """在日志行最前面加上 [文件标识]，没有标识时不加"""

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        file_id = getattr(record, "file_id", "")
        if file_id:
            return f"[{file_id}] {line}"
        return line


def setup_logging(config: Optional[Dict[str, Any]] = None) -> None:
    """
    设置日志记录

    Args:
        config: 日志配置，包含log_level、log_file、console_log、file_log等
    """
    # 默认配置
    default_config = {
        "log_level": "INFO",
        "log_file": "",
        "console_log": True,
        "file_log": False,
    }

    if config:
        default_config.update(config)

    # 获取根日志记录器
    root_logger = logging.getLogger()

    # 清除所有现有的处理器
    root_logger.handlers.clear()

    # 设置日志级别
    log_level = LOG_LEVELS.get(default_config["log_level"], logging.INFO)
    root_logger.setLevel(log_level)

    # 创建格式化器
    formatter = TaskIdFormatter(LOG_FORMAT, DATE_FORMAT)

    # 添加控制台处理器
    if default_config["console_log"]:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(TaskIdFilter())
        root_logger.addHandler(console_handler)

    # 添加文件处理器
    if default_config["file_log"]:
        log_file = default_config["log_file"]
        
        # 如果没有指定日志文件，使用默认路径
        if not log_file:
            # 尝试多个默认路径
            default_paths = [
                Path("logs/video-organizer.log"),
                Path(__file__).parent.parent / "logs" / "video-organizer.log",
            ]
            for p in default_paths:
                p.parent.mkdir(parents=True, exist_ok=True)
                log_file = str(p)
                break

        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)

        try:
            max_bytes = int(default_config.get("log_max_bytes", 10 * 1024 * 1024))
            backup_count = int(default_config.get("log_backup_count", 5))
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
            )
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(TaskIdFilter())
            root_logger.addHandler(file_handler)
            root_logger.info(f"日志文件已设置: {log_file} (maxBytes={max_bytes}, backupCount={backup_count})")
        except Exception as e:
            print(f"设置日志文件失败: {e}")

    # 抑制第三方库的日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # 记录初始化信息
    root_logger.info("日志系统初始化完成")


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        日志记录器实例
    """
    return logging.getLogger(name)


def log_exception(logger: logging.Logger, message: str, exc_info: bool = True) -> None:
    """
    记录异常信息

    Args:
        logger: 日志记录器
        message: 错误消息
        exc_info: 是否包含异常堆栈
    """
    logger.error(message, exc_info=exc_info)


def log_warning_with_details(
    logger: logging.Logger, message: str, details: Optional[Dict[str, Any]] = None
) -> None:
    """
    记录带有详细信息的警告

    Args:
        logger: 日志记录器
        message: 警告消息
        details: 详细信息字典
    """
    if details:
        details_str = ", ".join([f"{k}={v}" for k, v in details.items()])
        logger.warning(f"{message} - 详情: {details_str}")
    else:
        logger.warning(message)


def log_success(
    logger: logging.Logger, message: str, details: Optional[Dict[str, Any]] = None
) -> None:
    """
    记录成功信息

    Args:
        logger: 日志记录器
        message: 成功消息
        details: 详细信息字典
    """
    if details:
        details_str = ", ".join([f"{k}={v}" for k, v in details.items()])
        logger.info(f"✅ {message} - 详情: {details_str}")
    else:
        logger.info(f"✅ {message}")


def log_failure(
    logger: logging.Logger, message: str, error: Optional[Exception] = None
) -> None:
    """
    记录失败信息

    Args:
        logger: 日志记录器
        message: 失败消息
        error: 异常对象
    """
    if error:
        logger.error(f"❌ {message} - 错误: {str(error)}", exc_info=True)
    else:
        logger.error(f"❌ {message}")


def configure_log_rotation(
    file_path: str, max_bytes: int = 10485760, backup_count: int = 5
) -> logging.handlers.RotatingFileHandler:
    """
    配置日志轮转

    Args:
        file_path: 日志文件路径
        max_bytes: 单个日志文件最大字节数
        backup_count: 保留的备份文件数

    Returns:
        轮转文件处理器
    """
    formatter = TaskIdFormatter(LOG_FORMAT, DATE_FORMAT)
    handler = logging.handlers.RotatingFileHandler(
        file_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setFormatter(formatter)
    handler.addFilter(TaskIdFilter())
    return handler
