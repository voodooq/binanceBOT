import aiohttp
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class GeoCheckService:
    """
    地域合规预检服务。
    用于在 Bot 启动前检查当前代理/服务器出口 IP 是否在币安受限制区域。
    """
    
    # 币安主要限制的区域列表 (ISO 国家代码)
    # 常规限制包括：美国(US)、加拿大(CA)、中国(CN)、新加坡(SG)、马来西亚(MY)、日本(JP)、英国(GB)等
    PROHIBITED_COUNTRIES = {
        "US", "CA", "CN", "SG", "MY", "JP", "GB", "NL", "DE", "IT"
    }
    
    async def get_ip_info(self, proxy: Optional[str] = None) -> Optional[dict]:
        """获取当前出口 IP 的详细信息"""
        # 使用 ip-api.com 获取 JSON 格式的 IP 地理位置
        url = "http://ip-api.com/json"
        try:
            # 显式创建会话并应用代理
            async with aiohttp.ClientSession() as session:
                async with session.get(url, proxy=proxy, timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            logger.warning(f"[GeoCheck] 无法探测地理位置: {e}")
        return None

    async def is_compliant(self, proxy: Optional[str] = None) -> tuple[bool, str]:
        """
        检查当前环境是否合规。
        @return (是否合规, 提示信息)
        """
        from src.core.config import settings
        # 在测试网模式下，或者显式开启忽略开关时，跳过地理位置检查
        if settings.BINANCE_TESTNET or settings.IGNORE_GEO_CHECK:
            return True, "Geo-check bypassed (Testnet or IgnoreEnabled)"

        info = await self.get_ip_info(proxy)
        if not info:
            # 如果接口失效，我们选择警告通过。因为不合规在下单时币安也会返回错误。
            logger.warning("[GeoCheck] 地理位置 API 无法访问，跳过强制拦截。")
            return True, "无法探测 IP，跳过硬拦截"
            
        country_code = info.get("countryCode")
        region_name = info.get("regionName", "")
        ip = info.get("query")
        
        # 1. 国家级拦截
        if country_code in self.PROHIBITED_COUNTRIES:
            msg = f"🚫 地域合规性拦截: 检测到受限区域 {country_code} (IP: {ip})"
            logger.error(msg)
            return False, msg
            
        # 2. 特殊地区级别拦截 (例如安大略省: Ontario)
        if country_code == "CA" and "Ontario" in region_name:
             msg = f"🚫 地域合规性拦截: 加拿大安大略省受限 (IP: {ip})"
             logger.error(msg)
             return False, msg

        logger.info(f"✅ 地域预检通过: {country_code} ({info.get('country')}) | IP: {ip}")
        return True, "Compliant"

geo_check_service = GeoCheckService()
