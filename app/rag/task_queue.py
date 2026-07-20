"""
线程安全任务队列

协调多线程切片和单线程写入之间的数据传递。
用于文档处理管线中，多个线程并行切片文本，
然后通过线程安全的队列将结果传递给写入线程。
"""

import queue
import threading
from typing import Any, Optional


class TaskQueue:
    """
    线程安全的任务队列
    
    用于文档处理管线中协调多线程切片和单线程写入：
    - 多个生产者线程将切片结果放入队列
    - 单个消费者线程从队列取出并写入 ChromaDB
    - 支持超时和优雅关闭
    """
    
    def __init__(self, maxsize: int = 0):
        """
        初始化任务队列
        
        Args:
            maxsize: 队列最大容量，0 表示无限制
        """
        self._queue = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._done = False
    
    def put(self, item: Any, timeout: Optional[float] = None) -> None:
        """
        向队列中添加任务
        
        Args:
            item: 任务数据
            timeout: 超时时间（秒），None 表示阻塞直到有空间
        """
        if self._done:
            raise RuntimeError("队列已关闭，无法添加任务")
        self._queue.put(item, timeout=timeout)
    
    def get(self, timeout: Optional[float] = None) -> Optional[Any]:
        """
        从队列中获取任务
        
        Args:
            timeout: 超时时间（秒），None 表示阻塞直到有数据
            
        Returns:
            任务数据，超时或队列关闭返回 None
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def task_done(self) -> None:
        """标记一个任务已完成"""
        self._queue.task_done()
    
    def close(self) -> None:
        """关闭队列，不再接受新任务"""
        self._done = True
    
    def is_done(self) -> bool:
        """队列是否已关闭"""
        return self._done
    
    def is_empty(self) -> bool:
        """队列是否为空"""
        return self._queue.empty()
    
    def size(self) -> int:
        """获取队列当前大小"""
        return self._queue.qsize()
