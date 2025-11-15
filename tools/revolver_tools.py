from astrbot.api import FunctionTool, logger
from astrbot.api.event import AstrMessageEvent
from typing import Optional

CHAMBER_COUNT = 6


class BaseRevolverTool:
    """左轮手枪工具基类，包含通用辅助方法"""

    def _get_group_id(self, event: AstrMessageEvent) -> Optional[int]:
        """获取群ID"""
        return getattr(event.message_obj, "group_id", None)

    def _get_user_name(self, event: AstrMessageEvent) -> str:
        """获取用户昵称"""
        return event.get_sender_name() or "玩家"


class StartRevolverGameTool(FunctionTool, BaseRevolverTool):
    """AI触发器工具 - 启动左轮手枪游戏"""

    def __init__(self, plugin_instance=None):
        """初始化触发器工具

        Args:
            plugin_instance: 插件实例，用于触发游戏逻辑
        """
        self.name = "start_revolver_game"
        self.description = """TRIGGER TOOL: Triggers a new Russian Roulette game in the main plugin.

IMPORTANT: This is ONLY a trigger - the plugin handles all game logic, messaging, and user responses automatically.

DO NOT explain game rules, generate game results, or describe what happened. The plugin will send appropriate messages to users.

Use when user wants to play Russian Roulette or says: '来玩左轮手枪', '轮盘赌', '再来一局', 'start game'."""
        self.parameters = {
            "type": "object",
            "properties": {
                "bullets": {
                    "type": "integer",
                    "description": "Number of bullets to load (1-6). Only admins can specify bullets. If not provided, will load random bullets automatically.",
                    "minimum": 1,
                    "maximum": 6,
                }
            },
            "required": [],
        }
        self.plugin = plugin_instance

    async def run(self, event: AstrMessageEvent, bullets: Optional[int] = None) -> str:
        """触发游戏启动 - 让主插件处理所有逻辑"""
        try:
            if not hasattr(self.plugin, "ai_start_game"):
                return "SYSTEM_ERROR: Plugin method unavailable"

            await self.plugin.ai_start_game(event, bullets)
            return "TRIGGER_SUCCESS: Game start request processed by plugin"

        except Exception as e:
            logger.error(f"Game start trigger failed: {e}")
            return "SYSTEM_ERROR: Failed to trigger game start"


class JoinRevolverGameTool(FunctionTool, BaseRevolverTool):
    """AI触发器工具 - 参与左轮手枪游戏"""

    def __init__(self, plugin_instance=None):
        """初始化触发器工具

        Args:
            plugin_instance: 插件实例，用于触发游戏逻辑
        """
        self.name = "join_revolver_game"
        self.description = """TRIGGER TOOL: Triggers a shot in the current Russian Roulette game.

IMPORTANT: This is ONLY a trigger - the plugin handles all shot logic, hit/miss determination, and user responses automatically.

DO NOT explain shot results, describe what happened, or generate game messages. The plugin will send appropriate messages to users.

Use when user wants to shoot or says: '我要玩', '我也要玩', '开枪', 'shoot', '我来试试'."""
        self.parameters = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        self.plugin = plugin_instance

    async def run(self, event: AstrMessageEvent) -> str:
        """触发开枪 - 让主插件处理所有逻辑"""
        try:
            if not hasattr(self.plugin, "ai_join_game"):
                return "SYSTEM_ERROR: Plugin method unavailable"

            await self.plugin.ai_join_game(event)
            return "TRIGGER_SUCCESS: Shot request processed by plugin"

        except Exception as e:
            logger.error(f"Shot trigger failed: {e}")
            return "SYSTEM_ERROR: Failed to trigger shot"


class CheckRevolverStatusTool(FunctionTool, BaseRevolverTool):
    """AI触发器工具 - 查询左轮手枪游戏状态"""

    def __init__(self, plugin_instance=None):
        """初始化触发器工具

        Args:
            plugin_instance: 插件实例，用于触发游戏逻辑
        """
        self.name = "check_revolver_status"
        self.description = """TRIGGER TOOL: Triggers a status check for the current Russian Roulette game.

IMPORTANT: This is ONLY a trigger - the plugin handles all status retrieval and user responses automatically.

DO NOT explain game status, describe remaining bullets, or generate status messages. The plugin will send appropriate status information to users.

Use when user asks about game status or says: '游戏状态', '状态', 'status', '游戏情况', '现在什么情况'."""
        self.parameters = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        self.plugin = plugin_instance

    async def run(self, event: AstrMessageEvent) -> str:
        """触发状态查询 - 让主插件处理所有逻辑"""
        try:
            if not hasattr(self.plugin, "ai_check_status"):
                return "SYSTEM_ERROR: Plugin method unavailable"

            await self.plugin.ai_check_status(event)
            return "TRIGGER_SUCCESS: Status check request processed by plugin"

        except Exception as e:
            logger.error(f"Status check trigger failed: {e}")
            return "SYSTEM_ERROR: Failed to trigger status check"
