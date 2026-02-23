"""
币安交易机器人 — 日志系统

提供结构化日志、控制台彩色输出、文件轮转和敏感信息自动脱敏。
"""
import logging
import logging.handlers
import re
from pathlib import Path

# NOTE: 需要脱敏的关键字段模式（API 密钥、密码等）
_SENSITIVE_PATTERNS = [
    re.compile(r'(api[_\s]?key["\s:=]+)([A-Za-z0-9]{8,})', re.IGNORECASE),
    re.compile(r'(api[_\s]?secret["\s:=]+)([A-Za-z0-9]{8,})', re.IGNORECASE),
    re.compile(r'(token["\s:=]+)([A-Za-z0-9:_-]{10,})', re.IGNORECASE),
]


class SensitiveFilter(logging.Filter):
    """
    日志过滤器：自动将日志中出现的敏感信息替换为脱敏值。
    防止 API 密钥等通过日志泄露。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern in _SENSITIVE_PATTERNS:
                record.msg = pattern.sub(
                    lambda m: m.group(1) + "****" + m.group(2)[-4:],
                    record.msg,
                )
        return True


class ColorFormatter(logging.Formatter):
    """
    控制台彩色日志格式化器。
    不同级别使用不同 ANSI 颜色，提升可读性。
    """

    COLORS = {
        logging.DEBUG: "\033[36m",     # 青色
        logging.INFO: "\033[32m",      # 绿色
        logging.WARNING: "\033[33m",   # 黄色
        logging.ERROR: "\033[31m",     # 红色
        logging.CRITICAL: "\033[35m",  # 紫色
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setupLogger(
    logLevel: str = "INFO",
    logDir: str | None = None,
    maxBytes: int = 10 * 1024 * 1024,  # 10MB
    backupCount: int = 5,
) -> None:
    """
    初始化全局日志系统。

    @param logLevel 日志级别 (DEBUG/INFO/WARNING/ERROR)
    @param logDir 日志文件目录，默认为项目根目录下的 logs/
    @param maxBytes 单个日志文件最大字节数
    @param backupCount 保留的历史日志文件数量
    """
    # 确定日志目录
    if logDir is None:
        logDir = str(Path(__file__).resolve().parent.parent.parent / "logs")
    Path(logDir).mkdir(parents=True, exist_ok=True)

    rootLogger = logging.getLogger()
    rootLogger.setLevel(getattr(logging, logLevel.upper(), logging.INFO))

    # 清除已有的 handler，防止重复添加
    rootLogger.handlers.clear()

    # --- 控制台 Handler ---
    consoleHandler = logging.StreamHandler()
    consoleHandler.setLevel(logging.DEBUG)
    consoleFormatter = ColorFormatter(
        fmt="%(asctime)s │ %(levelname)-18s │ %(name)-25s │ %(message)s",
        datefmt="%H:%M:%S",
    )
    consoleHandler.setFormatter(consoleFormatter)
    consoleHandler.addFilter(SensitiveFilter())
    rootLogger.addHandler(consoleHandler)

    # --- 文件 Handler（轮转） ---
    logFile = str(Path(logDir) / "bot.log")
    fileHandler = logging.handlers.RotatingFileHandler(
        logFile,
        maxBytes=maxBytes,
        backupCount=backupCount,
        encoding="utf-8",
    )
    fileHandler.setLevel(logging.DEBUG)
    fileFormatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fileHandler.setFormatter(fileFormatter)
    fileHandler.addFilter(SensitiveFilter())
    rootLogger.addHandler(fileHandler)

    logging.getLogger(__name__).info(
        "📝 日志系统初始化完成 (级别: %s, 文件: %s)", logLevel, logFile
    )
