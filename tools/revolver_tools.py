from astrbot.api import FunctionTool
from astrbot.api.event import AstrMessageEvent
from typing import Optional
import random
import datetime

CHAMBER_COUNT = 6


class BaseRevolverTool:
    """左轮手枪工具基类，包含通用辅助方法"""

    def _get_group_id(self, event: AstrMessageEvent) -> Optional[int]:
        """获取群ID"""
        return getattr(event.message_obj, "group_id", None)

    def _get_user_name(self, event: AstrMessageEvent) -> str:
        """获取用户昵称"""
        return event.get_sender_name() or "玩家"

    def _get_text_manager(self):
        """获取文本管理器实例"""
        if hasattr(self.plugin, 'text_manager'):
            return self.plugin.text_manager
        # 回退到全局text_manager
        from ..text_manager import text_manager as fallback
        return fallback


class StartRevolverGameTool(FunctionTool, BaseRevolverTool):
    """AI启动左轮手枪游戏的工具类"""

    def __init__(self, plugin_instance=None):
        """初始化工具

        Args:
            plugin_instance: 插件实例，用于访问禁言等方法
        """
        self.name = "start_revolver_game"
        self.description = """Start a new game of Russian Roulette. Use this when user wants to play, start a new round, or says '再来一局' (play again). If bullet count is not specified, random bullets (1-6) will be loaded.
        
        CRITICAL INSTRUCTION: When you receive the result from this tool, you must output it EXACTLY as given without ANY modification, rephrasing, or adding personal commentary. Do NOT add phrases like '我来帮你' or '游戏开始了' - just output the tool's result directly."""
        self.parameters = {
            "type": "object",
            "properties": {
                "bullets": {
                    "type": "integer",
                    "description": "Number of bullets to load (1-6). If not provided, will load random bullets.",
                    "minimum": 1,
                    "maximum": 6,
                }
            },
            "required": [],
        }
        self.plugin = plugin_instance

    def _get_random_bullet_count(self) -> int:
        """获取随机子弹数量"""
        return random.randint(1, CHAMBER_COUNT)

    def _create_chambers(self, bullet_count: int):
        """创建弹膛状态"""
        chambers = [False] * CHAMBER_COUNT
        if bullet_count > 0:
            positions = random.sample(range(CHAMBER_COUNT), bullet_count)
            for pos in positions:
                chambers[pos] = True
        return chambers

    async def run(self, event: AstrMessageEvent, bullets: Optional[int] = None) -> str:
        """启动游戏逻辑"""
        try:
            group_id = self._get_group_id(event)
            if not group_id:
                return "❌ 仅限群聊使用"

            # 检查现有游戏
            if group_id in self.plugin.group_games:
                return "💥 游戏还在进行中！"

            # 确定子弹数量
            if bullets is None or not (1 <= bullets <= CHAMBER_COUNT):
                bullets = self._get_random_bullet_count()

            # 创建游戏
            chambers = self._create_chambers(bullets)
            self.plugin.group_games[group_id] = {
                "chambers": chambers,
                "current": 0,
                "start_time": datetime.datetime.now(),
            }

            # 启动超时机制
            if self.plugin and hasattr(self.plugin, "_start_timeout"):
                await self.plugin._start_timeout(event, group_id)

            user_name = self._get_user_name(event)
            load_msg = self._get_text_manager().get_text("load_messages", sender_nickname=user_name)
            return f"🎯 {user_name} 挑战命运！\n🔫 {load_msg}\n💀 谁敢扣动扳机？"
        except Exception as e:
            return f"❌ Failed to start game: {str(e)}"


class JoinRevolverGameTool(FunctionTool, BaseRevolverTool):
    """AI参与左轮手枪游戏的工具类"""

    def __init__(self, plugin_instance=None):
        """初始化工具

        Args:
            plugin_instance: 插件实例，用于访问禁言等方法
        """
        self.name = "join_revolver_game"
        self.description = """Join the current Russian Roulette game by pulling the trigger. Use this when user says '我要玩', '我也要', '开枪', 'shoot', or wants to participate in an ongoing game.
        
        CRITICAL INSTRUCTION: When you receive the result from this tool, you must output it EXACTLY as given without ANY modification, rephrasing, or adding personal touches. Even if the result contains emoji or specific phrasing, output it verbatim. Do NOT add explanations like '结果出来了' or '你开枪了' - just output the tool's result directly."""
        self.parameters = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "User's action to perform in the game. Common values: 'shoot' (开枪), 'join' (加入游戏), 'participate' (参与活动). If not specified, defaults to 'shoot'.",
                    "enum": ["shoot", "join", "participate"],
                }
            },
            "required": [],
        }
        self.plugin = plugin_instance

    async def run(self, event: AstrMessageEvent, action: str = "shoot") -> str:
        """参与游戏逻辑"""
        try:
            group_id = self._get_group_id(event)
            if not group_id:
                return "❌ 仅限群聊使用"

            game = self.plugin.group_games.get(group_id)
            if not game:
                return "⚠️ 没有游戏进行中\n💡 使用 /装填 开始游戏（随机装填）\n💡 管理员可使用 /装填 [数量] 指定子弹"

            user_name = self._get_user_name(event)
            user_id = int(event.get_sender_id())

            chambers = game["chambers"]
            current = game["current"]

            if chambers[current]:
                # 中弹
                chambers[current] = False
                game["current"] = (current + 1) % CHAMBER_COUNT

                # 如果有插件实例，检查是否可禁言
                if self.plugin and hasattr(self.plugin, "_is_user_bannable"):
                    # 检查是否可禁言（管理员/群主免疫）
                    if not await self.plugin._is_user_bannable(event, user_id):
                        # 管理员/群主免疫
                        result = f"💥 {user_name} 中弹！\n⚠️ 管理员/群主免疫！"
                    else:
                        # 普通用户，执行禁言
                        ban_duration = await self.plugin._ban_user(event, user_id)
                        if ban_duration > 0:
                            formatted_duration = self.plugin._format_ban_duration(
                                ban_duration
                            )
                            trigger_msg = self._get_text_manager().get_text("trigger_descriptions")
                            result = f"💥 {trigger_msg}\n🔇 禁言 {formatted_duration}"
                        else:
                            result = f"💥 {user_name} 中弹！\n⚠️ 禁言失败！"
                elif self.plugin and hasattr(self.plugin, "_ban_user"):
                    # 旧版本兼容，直接执行禁言
                    ban_duration = await self.plugin._ban_user(event, user_id)
                    if ban_duration > 0:
                        formatted_duration = self.plugin._format_ban_duration(
                            ban_duration
                        )
                        trigger_msg = self._get_text_manager().get_text("trigger_descriptions")
                        result = f"💥 {trigger_msg}\n🔇 禁言 {formatted_duration}"
                    else:
                        result = f"💥 {user_name} 中弹！\n⚠️ 管理员/群主免疫！"
                else:
                    # 没有插件实例，只返回文本
                    result = f"💥 {user_name} 中弹！\n🔇 接受惩罚..."
            else:
                # 空弹
                game["current"] = (current + 1) % CHAMBER_COUNT
                miss_msg = self._get_text_manager().get_text(
                    "miss_messages", sender_nickname=user_name
                )
                result = miss_msg

            # 检查结束
            if sum(chambers) == 0:
                # 清理超时任务（如果存在）
                if (
                    hasattr(self.plugin, "timeout_tasks")
                    and group_id in self.plugin.timeout_tasks
                ):
                    task = self.plugin.timeout_tasks[group_id]
                    if not task.done():
                        task.cancel()
                    # 确保从字典中移除（无论是否存在）
                    self.plugin.timeout_tasks.pop(group_id, None)

                # 清理游戏状态
                del self.plugin.group_games[group_id]
                end_msg = self._get_text_manager().get_text("game_end")
                result += f"\n🏁 {end_msg}！"

            return result
        except Exception as e:
            return f"❌ Failed to join game: {str(e)}"


class CheckRevolverStatusTool(FunctionTool, BaseRevolverTool):
    """AI查询左轮手枪游戏状态的工具类"""

    def __init__(self, plugin_instance=None):
        """初始化工具

        Args:
            plugin_instance: 插件实例，用于访问禁言等方法
        """
        self.name = "check_revolver_status"
        self.description = """Check the current status of the Russian Roulette game. Use this when user asks about game status, wants to know remaining bullets, or says '状态', 'status', '游戏情况'.
        
        CRITICAL INSTRUCTION: When you receive the result from this tool, you must output it EXACTLY as given without ANY modification, rephrasing, or adding personal commentary. Even if the result looks like '没有游戏进行中', output it directly. Do NOT add phrases like '根据查询' or '我来告诉你' - just output the tool's result verbatim."""
        self.parameters = {
            "type": "object",
            "properties": {
                "detailed": {
                    "type": "boolean",
                    "description": "Whether to return detailed game status including current chamber position and game history. If true, provides more comprehensive information. Default is false for basic status.",
                }
            },
            "required": [],
        }
        self.plugin = plugin_instance

    async def run(self, event: AstrMessageEvent, detailed: bool = False) -> str:
        """查询游戏状态逻辑"""
        try:
            group_id = self._get_group_id(event)
            if not group_id:
                return "❌ 仅限群聊使用"

            game = self.plugin.group_games.get(group_id)
            if not game:
                return "🔍 没有游戏进行中\n💡 使用 /装填 开始游戏（随机装填）\n💡 管理员可使用 /装填 [数量] 指定子弹"

            chambers = game["chambers"]
            current = game["current"]
            remaining = sum(chambers)

            status_msg = self._get_text_manager().get_text("game_status")
            danger = "🔴 危险" if chambers[current] else "🟢 安全"

            return (
                f"🔫 {status_msg}\n"
                f"📊 剩余：{remaining}发子弹\n"
                f"🎯 第{current + 1}膛\n"
                f"{danger}"
            )
        except Exception as e:
            return f"❌ Failed to check status: {str(e)}"
