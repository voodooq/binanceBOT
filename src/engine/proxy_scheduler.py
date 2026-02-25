import logging
import random
import os
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class ProxyScheduler:
    """
    分布式代理调度器。
    管理随机或加权的 SOCKS5/HTTP 代理池，分摊单一 IP 的频率压力。
    """
    def __init__(self, proxy_list: List[str] = None):
        # 内部代理池: {proxy_url: active_count}
        self._pool: Dict[str, int] = {}
        
        # 尝试从环境变量加载初始化列表 (格式: SOCKS5_PROXIES=http://1.1.1.1:80,http://2.2.2.2:80)
        env_proxies = os.getenv("BINANCE_PROXY_POOL", "")
        if env_proxies:
            for p in env_proxies.split(","):
                if p.strip():
                    self._pool[p.strip()] = 0
        
        # 如果构造函数传入了列表，则合并
        if proxy_list:
            for p in proxy_list:
                self._pool[p] = 0
        
        if self._pool:
            logger.info(f"📦 [ProxyScheduler] 代理池初始化完成，节点数量: {len(self._pool)}")

    def add_proxy(self, proxy_url: str):
        """动态向池中添加新的代理节点"""
        if proxy_url not in self._pool:
            self._pool[proxy_url] = 0
            logger.info(f"[ProxyScheduler] 已载入新代理节点: {proxy_url}")
            
    def get_best_proxy(self) -> Optional[str]:
        """按最小载荷分配代理并递增计数"""
        if not self._pool:
            return None
            
        # 1. 寻找当前使用最少的代理 (Least Loaded)
        sorted_proxies = sorted(self._pool.items(), key=lambda x: x[1])
        min_count = sorted_proxies[0][1]
        
        # 2. 随机挑选一个使用率同为最低的，防止“堆积”在第一个
        candidates = [p for p, c in self._pool.items() if c == min_count]
        chosen = random.choice(candidates)
        
        # 3. 递增该代理的载荷计数
        self._pool[chosen] += 1
        
        logger.info(f"🚀 [ProxyScheduler] 成功分配代理: {chosen} (当前总载荷: {self._pool[chosen]})")
        return chosen

    def release_proxy(self, proxy_url: Optional[str]):
        """当 Bot 停止时，释放代理占用的载荷计数"""
        if proxy_url and proxy_url in self._pool:
            self._pool[proxy_url] = max(0, self._pool[proxy_url] - 1)
            logger.info(f"♻️ [ProxyScheduler] 代理已回收: {proxy_url} (剩余载荷: {self._pool[proxy_url]})")

    async def start_health_check(self):
        """[P3] 启动代理周期性探活任务"""
        while True:
            if self._pool:
                tasks = [self._check_node(p) for p in self._pool.keys()]
                await asyncio.gather(*tasks)
            await asyncio.sleep(60) # 每分钟探活一次

    async def _check_node(self, proxy_url: str):
        """测试单个节点可用性，若失效则暂时剔除或标记"""
        import aiohttp
        try:
            connector = None
            if proxy_url.startswith("socks5"):
                from aiohttp_socks import ProxyConnector
                connector = ProxyConnector.from_url(proxy_url)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                # 访问币安 API 测试连通性
                async with session.get("https://api.binance.com/api/v3/ping", timeout=5) as resp:
                    if resp.status != 200:
                        raise Exception(f"Status {resp.status}")
        except Exception as e:
            logger.warning(f"⚠️ [ProxyScheduler] 节点故障: {proxy_url} | 原因: {e}")
            # 这里可以根据需要将节点从 pool 中暂时移除或标记
            # 简单起见，如果连续失败多次，可以 pop 掉
            pass

    @property
    def total_capacity(self) -> int:
        return len(self._pool)

# 全局单例
proxy_scheduler = ProxyScheduler()
