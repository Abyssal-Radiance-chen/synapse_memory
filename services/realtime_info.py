"""
实时信息获取服务（全异步）
获取东八区时间、当前天气 + 未来天气预报
"""
import logging
from datetime import datetime
from typing import Dict, Any, List

import pytz
import httpx

import config

logger = logging.getLogger(__name__)


class RealtimeInfoService:
    """异步实时信息服务"""

    def __init__(self):
        self.timezone = pytz.timezone("Asia/Shanghai")
        self.weather_api_key = config.WEATHER_API_KEY
        self.weather_city = config.WEATHER_CITY

    def get_current_timestamp(self) -> str:
        """获取格式化时间戳"""
        now = datetime.now(self.timezone)
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekdays[now.weekday()]
        return now.strftime(f"%Y年%m月%d日 %H:%M {weekday}")

    def get_date_string(self) -> str:
        """获取日期字符串"""
        now = datetime.now(self.timezone)
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekdays[now.weekday()]
        return now.strftime(f"%Y年%m月%d日 {weekday}")

    async def get_weather_now(self) -> Dict[str, Any]:
        """获取当前天气（异步）"""
        try:
            url = "https://api.seniverse.com/v3/weather/now.json"
            params = {
                "key": self.weather_api_key,
                "location": self.weather_city,
                "language": "zh-Hans",
                "unit": "c",
            }
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=5)
                response.raise_for_status()
                data = response.json()

            if data.get("results") and len(data["results"]) > 0:
                result = data["results"][0]
                location = result.get("location", {})
                now = result.get("now", {})
                return {
                    "city": location.get("name", self.weather_city),
                    "temperature": now.get("temperature"),
                    "description": now.get("text", ""),
                }
            return {"city": self.weather_city, "temperature": None, "description": "未获取到"}
        except Exception as e:
            logger.warning(f"当前天气获取失败: {e}")
            return {"city": self.weather_city, "temperature": None, "description": "获取失败"}

    async def get_weather_forecast(self, days: int = 2) -> List[Dict[str, Any]]:
        """获取未来天气预报（异步）"""
        try:
            url = "https://api.seniverse.com/v3/weather/daily.json"
            params = {
                "key": self.weather_api_key,
                "location": self.weather_city,
                "language": "zh-Hans",
                "unit": "c",
                "start": "0",
                "days": str(days),
            }
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=5)
                response.raise_for_status()
                data = response.json()

            forecasts = []
            if data.get("results") and len(data["results"]) > 0:
                daily_list = data["results"][0].get("daily", [])
                for day in daily_list:
                    forecasts.append({
                        "date": day.get("date", ""),
                        "text_day": day.get("text_day", ""),
                        "text_night": day.get("text_night", ""),
                        "high": day.get("high", ""),
                        "low": day.get("low", ""),
                        "wind_direction": day.get("wind_direction", ""),
                        "wind_scale": day.get("wind_scale", ""),
                        "humidity": day.get("humidity", ""),
                    })
            return forecasts
        except Exception as e:
            logger.warning(f"天气预报获取失败: {e}")
            return []

    async def get_full_weather_string(self) -> str:
        """
        获取完整天气信息字符串（当前天气 + 未来预报）
        供 prompt 注入使用
        """
        # 并发获取当前天气和预报
        import asyncio
        now_task = self.get_weather_now()
        forecast_task = self.get_weather_forecast(days=2)
        weather_now, forecasts = await asyncio.gather(now_task, forecast_task)

        parts = []

        # 当前天气
        city = weather_now.get("city", self.weather_city)
        temp = weather_now.get("temperature")
        desc = weather_now.get("description", "")
        if temp is not None:
            parts.append(f"当前天气: {city} {temp}°C {desc}")
        else:
            parts.append(f"当前天气: {city} {desc}")

        # 未来预报
        if forecasts:
            for f in forecasts:
                date_str = f["date"]
                parts.append(
                    f"{date_str}: 白天{f['text_day']} 夜间{f['text_night']} "
                    f"{f['low']}~{f['high']}°C {f['wind_direction']}风{f['wind_scale']}级 "
                    f"湿度{f['humidity']}%"
                )

        return "\n".join(parts)

    async def get_event_time_weather(self) -> Dict[str, str]:
        """获取事件级别的时间和天气（异步）"""
        return {
            "date": self.get_date_string(),
            "weather": await self.get_full_weather_string(),
        }
