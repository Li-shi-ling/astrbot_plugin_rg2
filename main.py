import asyncio
import datetime
import random

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

# 插件元数据
PLUGIN_NAME = "astrbot_plugin_rg2"
PLUGIN_AUTHOR = "piexian"
PLUGIN_DESCRIPTION = (
    "一个刺激的群聊轮盘赌游戏插件，支持管理员装填子弹、用户开枪对决、随机走火等功能"
)
PLUGIN_VERSION = "1.1.0"  # 默认版本，将从metadata.yaml读取
PLUGIN_REPO = "https://github.com/piexian/astrbot_plugin_rg2"

# 文本管理器（延迟初始化）
text_manager = None

# 导入事件类型
try:
    from astrbot.core.star.filter.event_message_type import EventMessageType
except ImportError:
    # 兼容旧版本
    EventMessageType = None

DEFAULT_CHAMBER_COUNT = 6
DEFAULT_TIMEOUT = 300
DEFAULT_MISFIRE_PROB = 0.003
DEFAULT_MIN_BAN = 60
DEFAULT_MAX_BAN = 300
DEFAULT_MAX_BULLET_COUNT = 6
DEFAULT_FIXED_BULLET_COUNT = 0
DEFAULT_NO_FULL_CHAMBER = False
DEFAULT_END_ON_FULL_ROTATION = False
DEFAULT_HIDE_BULLET_COUNT = False


@register(
    PLUGIN_NAME,
    PLUGIN_AUTHOR,
    PLUGIN_DESCRIPTION,
    PLUGIN_VERSION,
    PLUGIN_REPO,
)
class RevolverGunPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        """初始化左轮手枪插件

        Args:
            context: AstrBot上下文对象
            config: 插件配置字典
        """
        super().__init__(context)
        self.context = context
        self.config = config or {}

        # 读取插件版本
        self._load_plugin_version()

        # 游戏状态管理
        self.group_games: dict[int, dict] = {}
        self.group_misfire: dict[int, bool] = {}
        self.timeout_tasks: dict[int, asyncio.Task] = {}

        # AI触发器事件队列
        self.ai_trigger_queue: dict[str, dict] = {}
        self.ai_trigger_counter = 0  # 用于生成一致的ID

        # 数据持久化
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_rg2")
        self.config_file = self.data_dir / "group_misfire.json"

        # 加载持久化配置
        self._load_misfire_config()

        # 初始化文本管理器
        self._init_text_manager()

        # 配置参数
        self.timeout = self.config.get("timeout_seconds", DEFAULT_TIMEOUT)
        self.misfire_prob = self.config.get("misfire_probability", DEFAULT_MISFIRE_PROB)
        self.min_ban = self.config.get("min_ban_seconds", DEFAULT_MIN_BAN)
        self.max_ban = self.config.get("max_ban_seconds", DEFAULT_MAX_BAN)
        self.default_misfire = self.config.get("misfire_enabled_by_default", False)
        self.ai_trigger_delay = self.config.get(
            "ai_trigger_delay", 2
        )  # AI工具触发延迟（秒）

        # 新增配置参数
        self.max_bullet_count = self.config.get(
            "max_bullet_count", DEFAULT_MAX_BULLET_COUNT
        )
        self.chamber_count = self.config.get("chamber_count", self.max_bullet_count)

        self.stuck_probability = self.config.get("stuck", 0)

        # 验证配置有效性
        if self.chamber_count < 1:
            raise ValueError(f"chamber_count 必须 >= 1，当前值: {self.chamber_count}")
        if self.max_bullet_count < 1:
            raise ValueError(
                f"max_bullet_count 必须 >= 1，当前值: {self.max_bullet_count}"
            )
        if self.max_bullet_count > self.chamber_count:
            raise ValueError(
                f"max_bullet_count({self.max_bullet_count}) 不能超过 chamber_count({self.chamber_count})"
            )
        self.fixed_bullet_count = self.config.get(
            "fixed_bullet_count", DEFAULT_FIXED_BULLET_COUNT
        )
        self.no_full_chamber = self.config.get(
            "no_full_chamber", DEFAULT_NO_FULL_CHAMBER
        )
        self.end_on_full_rotation = self.config.get(
            "end_on_full_rotation", DEFAULT_END_ON_FULL_ROTATION
        )
        self.hide_bullet_count = self.config.get(
            "hide_bullet_count", DEFAULT_HIDE_BULLET_COUNT
        )

        # 注册函数工具
        self._register_function_tools()

    def _load_plugin_version(self):
        """从metadata.yaml读取插件版本"""
        try:
            import os

            import yaml

            # 获取插件目录路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            metadata_path = os.path.join(current_dir, "metadata.yaml")

            if os.path.exists(metadata_path):
                with open(metadata_path, encoding="utf-8") as f:
                    metadata = yaml.safe_load(f)
                    self.plugin_version = metadata.get("version", PLUGIN_VERSION)
                    logger.info(f"插件版本从metadata.yaml读取: {self.plugin_version}")
            else:
                self.plugin_version = PLUGIN_VERSION
                logger.warning(
                    f"未找到metadata.yaml，使用默认版本: {self.plugin_version}"
                )

        except Exception as e:
            self.plugin_version = PLUGIN_VERSION
            logger.error(f"读取插件版本失败，使用默认版本: {e}")

    def _init_text_manager(self):
        """初始化文本管理器"""
        global text_manager
        try:
            from .text_manager import TextManager

            self.text_manager = TextManager(config=self.config)
            text_manager = self.text_manager
            logger.info("文本管理器初始化成功")
        except Exception as e:
            logger.error(f"文本管理器初始化失败: {e}")

            # 使用默认文本管理器（空实现）
            class DummyTextManager:
                def get_text(self, category, **kwargs):
                    return ""

            text_manager = DummyTextManager()

    def _register_function_tools(self):
        """注册函数工具到AstrBot"""
        try:
            from .tools.revolver_game_tool import RevolverGameTool

            # 初始化统一工具并传递插件实例
            revolver_tool = RevolverGameTool(plugin_instance=self)

            # >= v4.5.1 使用新的注册方式
            if hasattr(self.context, "add_llm_tools"):
                self.context.add_llm_tools(revolver_tool)
            else:
                # < v4.5.1 兼容旧版本
                tool_mgr = self.context.provider_manager.llm_tools
                tool_mgr.func_list.append(revolver_tool)

            logger.info("左轮手枪统一触发器工具注册成功")
        except Exception as e:
            logger.error(f"注册函数工具失败: {e}", exc_info=True)

    def _get_group_id(self, event: AstrMessageEvent) -> int | None:
        """获取群ID

        Args:
            event: 消息事件对象

        Returns:
            群ID，如果不在群聊中返回None
        """
        # 首先尝试从 message_obj 获取（普通消息）
        group_id = getattr(event.message_obj, "group_id", None)
        if group_id:
            return group_id

        # 如果失败，尝试从 unified_msg_origin 解析（LLM工具调用）
        try:
            origin = getattr(event, "unified_msg_origin", "")
            if origin and ":group:" in origin:
                # 格式: platform_name:group:group_id
                parts = origin.split(":")
                if len(parts) >= 3:
                    return int(parts[2])
        except (ValueError, AttributeError):
            pass

        return None

    def _get_user_name(self, event: AstrMessageEvent) -> str:
        """获取用户昵称

        Args:
            event: 消息事件对象

        Returns:
            用户昵称，如果获取失败返回"玩家"
        """
        return event.get_sender_name() or "玩家"

    async def _is_group_admin(self, event: AstrMessageEvent) -> bool:
        """检查用户是否是群管理员

        Args:
            event: 消息事件对象

        Returns:
            是否是群管理员
        """
        try:
            group_id = self._get_group_id(event)
            if not group_id:
                return False

            user_id = int(event.get_sender_id())

            # 检查是否是bot超级管理员
            if event.is_admin():
                return True

            # 调用napcat接口获取群成员信息
            if hasattr(event.bot, "get_group_member_info"):
                member_info = await event.bot.get_group_member_info(
                    group_id=group_id, user_id=user_id, no_cache=True
                )

                # 检查角色：owner(群主) 或 admin(管理员)
                role = (
                    member_info.get("role", "")
                    if isinstance(member_info, dict)
                    else getattr(member_info, "role", "")
                )
                return role in ["owner", "admin"]

            return False
        except Exception as e:
            logger.error(f"检查群管理员权限失败: {e}")
            return False

    def _init_group(self, group_id: int):
        """初始化群状态

        Args:
            group_id: 群ID
        """
        if group_id not in self.group_misfire:
            self.group_misfire[group_id] = self.default_misfire

    def _load_misfire_config(self):
        """加载走火配置"""
        try:
            import json

            if self.config_file.exists():
                with open(self.config_file, encoding="utf-8") as f:
                    data = json.load(f)
                    self.group_misfire.update(data)
                logger.info(f"已加载 {len(data)} 个群的走火配置")
            else:
                logger.info("未找到走火配置文件，使用默认配置")
        except Exception as e:
            logger.error(f"加载走火配置失败: {e}")

    def _save_misfire_config(self):
        """保存走火配置"""
        try:
            import json

            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.group_misfire, f, ensure_ascii=False, indent=2)
            logger.debug(f"已保存 {len(self.group_misfire)} 个群的走火配置")
        except Exception as e:
            logger.error(f"保存走火配置失败: {e}")

    def _create_chambers(self, bullet_count: int, max_bullet:int = -1) -> list[bool]:
        """创建弹膛状态

        Args:
            bullet_count: 子弹数量

        Returns:
            弹膛状态列表，True表示有子弹
        """
        if max_bullet < 0:
            max_bullet = self.max_bullet_count
        max_bullet = min(max_bullet, 128)
        chambers = [False] * max_bullet
        if bullet_count > 0:
            positions = random.sample(range(max_bullet), min(bullet_count, len(chambers)))
            for pos in positions:
                chambers[pos] = True
        logger.debug(f"[_create_chambers] chambers:{chambers}")
        return chambers

    def _get_random_bullet_count(self) -> int:
        """获取随机子弹数量

        根据配置决定随机范围：
        - 如果设置了固定数量，返回固定值
        - 如果开启了禁止满膛，最大值为 max_bullet_count - 1
        - 否则范围为 1 到 max_bullet_count

        Returns:
            子弹数量
        """
        # 如果设置了固定装弹数量
        if self.fixed_bullet_count > 0:
            return min(self.fixed_bullet_count, self.max_bullet_count)

        # 计算随机范围
        max_count = self.max_bullet_count
        if self.no_full_chamber and max_count > 1:
            max_count -= 1

        return random.randint(1, max_count)

    def _parse_bullet_count(self, message: str) -> int | None:
        """解析子弹数量

        Args:
            message: 用户输入的消息

        Returns:
            解析出的子弹数量，如果解析失败返回None
        """
        parts = message.strip().split()
        if len(parts) < 2:
            return None

        try:
            count = int(parts[1])
            max_allowed = (
                self.chamber_count - 1 if self.no_full_chamber else self.chamber_count
            )
            if 1 <= count <= max_allowed:
                return count
        except (ValueError, IndexError):
            pass
        return None

    def _check_misfire(self, group_id: int) -> bool:
        """检查是否触发随机走火

        Args:
            group_id: 群ID

        Returns:
            是否触发走火
        """
        if not self.group_misfire.get(group_id, False):
            return False
        return random.random() < self.misfire_prob

    def _check_game_end(self, game: dict) -> bool:
        """检查游戏是否应该结束

        Args:
            game: 游戏状态字典

        Returns:
            是否应该结束游戏
        """
        chambers = game.get("chambers", [])
        remaining = sum(chambers)

        if remaining == 0:
            return True

        if self.end_on_full_rotation:
            shot_count = game.get("shot_count", 0)
            remaining_chambers = self.chamber_count - (shot_count % self.chamber_count)
            if remaining == remaining_chambers:
                return True

        return False

    def _cleanup_game(self, group_id: int):
        """清理游戏状态和超时任务

        Args:
            group_id: 群ID
        """
        if group_id in self.timeout_tasks:
            self.timeout_tasks[group_id].cancel()
            del self.timeout_tasks[group_id]
        self.group_games.pop(group_id, None)

    async def _is_user_bannable(self, event: AstrMessageEvent, user_id: int) -> bool:
        """检查用户是否可以被禁言（不是群主或管理员）

        Args:
            event: 消息事件对象
            user_id: 要检查的用户ID

        Returns:
            是否可以被禁言
        """
        try:
            group_id = self._get_group_id(event)
            if not group_id:
                return False

            # 调用API获取群成员信息
            if hasattr(event.bot, "get_group_member_info"):
                member_info = await event.bot.get_group_member_info(
                    group_id=group_id, user_id=user_id, no_cache=True
                )

                # 检查角色
                role = (
                    member_info.get("role", "member")
                    if isinstance(member_info, dict)
                    else getattr(member_info, "role", "member")
                )

                # 群主和管理员不能被禁言
                if role in ["owner", "admin"]:
                    logger.info(f"用户 {user_id} 是{role}，跳过禁言")
                    return False

                return True

            # 如果无法获取信息，默认可以禁言（兼容旧版本）
            return True
        except Exception as e:
            logger.error(f"检查用户可禁言状态失败: {e}")
            # 出错时默认可以禁言，避免游戏卡住
            return True

    def _format_ban_duration(self, seconds: int) -> str:
        """格式化禁言时长显示

        Args:
            seconds: 禁言时长（秒）

        Returns:
            格式化后的时长字符串
        """
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            if remaining_seconds > 0:
                return f"{minutes}分{remaining_seconds}秒"
            else:
                return f"{minutes}分钟"
        else:
            hours = seconds // 3600
            remaining_minutes = (seconds % 3600) // 60
            if remaining_minutes > 0:
                return f"{hours}小时{remaining_minutes}分钟"
            else:
                return f"{hours}小时"

    async def _ban_user(self, event: AstrMessageEvent, user_id: int) -> int:
        """禁言用户

        Args:
            event: 消息事件对象
            user_id: 要禁言的用户ID

        Returns:
            禁言时长（秒），如果禁言失败返回 0
        """
        group_id = self._get_group_id(event)
        if not group_id:
            logger.warning("❌ 无法获取群ID，跳过禁言")
            return 0

        # 检查是否可以禁言该用户
        if not await self._is_user_bannable(event, user_id):
            user_name = self._get_user_name(event)
            logger.info(f"⏭️ 用户 {user_name}({user_id}) 是管理员/群主，跳过禁言")
            return 0

        duration = random.randint(self.min_ban, self.max_ban)
        formatted_duration = self._format_ban_duration(duration)

        try:
            if hasattr(event.bot, "set_group_ban"):
                logger.info(f"🎯 正在禁言用户 {user_id}，时长 {formatted_duration}")
                await event.bot.set_group_ban(
                    group_id=group_id, user_id=user_id, duration=duration
                )
                logger.info(
                    f"✅ 用户 {user_id} 在群 {group_id} 被禁言 {formatted_duration}"
                )
                return duration
            else:
                logger.error("❌ Bot 没有 set_group_ban 方法，无法禁言")
                logger.error("💡 提示：请检查机器人适配器是否支持禁言功能")
        except Exception as e:
            logger.error(f"❌ 禁言用户失败: {e}", exc_info=True)
            # 检查是否是权限问题
            error_msg = str(e).lower()
            if any(
                keyword in error_msg
                for keyword in ["permission", "权限", "privilege", "insufficient"]
            ):
                logger.error("🔐 权限不足：请检查机器人是否有群管理权限！")
                logger.error("💡 解决方法：将机器人设置为群管理员")

        return 0

    # ========== 独立指令 ==========

    @filter.command("装填")
    async def load_bullets(self, event: AstrMessageEvent, bullet_count:int = -1, max_bullet:int = -1):
        """装填子弹

        用法: [指令前缀]装填 [数量]
        不指定数量则随机装填1-6发子弹（所有用户可用）
        指定数量则装填固定子弹（仅限管理员）
        """
        try:
            group_id = self._get_group_id(event)
            if not group_id:
                yield event.plain_result("❌ 仅限群聊使用")
                return

            self._init_group(group_id)
            user_name = self._get_user_name(event)

            # 检查是否已有游戏
            if group_id in self.group_games:
                yield event.plain_result(f"💥 {user_name}，游戏还在进行中！")
                return

            # 解析子弹数量
            # bullet_count = self._parse_bullet_count(event.message_str or "")

            logger.debug(f"[装填] bullet_count:{bullet_count}, max_bullet:{max_bullet}")

            # 如果指定了子弹数量，检查是否是管理员
            if bullet_count < 0:
                bullet_count = self._get_random_bullet_count()

            # 创建游戏
            max_bullet = self.max_bullet_count if max_bullet < 0 else max_bullet
            chambers = self._create_chambers(bullet_count, max_bullet)
            self.group_games[group_id] = {
                "chambers": chambers,
                "current": 0,
                "start_time": datetime.datetime.now(),
                "shot_count": 0,  # 记录已射击次数，用于弹膛轮转结束判断
            }

            # 设置超时
            await self._start_timeout(event, group_id)

            logger.info(f"用户 {user_name} 在群 {group_id} 装填 {bullet_count} 发子弹")

            # 构建装填消息
            if self.hide_bullet_count:
                # 隐藏子弹数量
                load_msg = text_manager.get_text(
                    "load_messages", sender_nickname=user_name, bullet_count="?"
                )
            else:
                load_msg = text_manager.get_text(
                    "load_messages",
                    sender_nickname=user_name,
                    bullet_count=bullet_count,
                )
            yield event.plain_result(
                f"🔫 {load_msg}\n"
                f"💀 {max_bullet} 弹膛，生死一线！\n"
                f"⚡ 限时 {self.timeout} 秒！"
            )
        except Exception as e:
            logger.error(f"装填子弹失败: {e}")
            yield event.plain_result("❌ 装填失败，请重试")

    @filter.command("开枪")
    async def shoot(self, event: AstrMessageEvent):
        """扣动扳机

        用法: [指令前缀]开枪
        参与当前游戏的射击，可能中弹或空弹
        """
        try:
            group_id = self._get_group_id(event)
            if not group_id:
                yield event.plain_result("❌ 仅限群聊使用")
                return

            self._init_group(group_id)
            user_name = self._get_user_name(event)
            user_id = int(event.get_sender_id())

            # 检查游戏状态
            game = self.group_games.get(group_id)
            if not game:
                yield event.plain_result(f"⚠️ {user_name}，枪里没子弹！")
                return

            # 重置超时
            await self._start_timeout(event, group_id)

            # 执行射击
            chambers = game["chambers"]
            current = game["current"]

            # 增加射击计数
            game["shot_count"] = game.get("shot_count", 0) + 1

            if chambers[current]:
                # 中弹
                chambers[current] = False
                game["current"] = (current + 1) % len(chambers)

                # 检查是否可禁言（管理员/群主免疫）
                if not await self._is_user_bannable(event, user_id):
                    # 管理员/群主免疫，直接显示免疫提示
                    logger.info(
                        f"⏭️ 用户 {user_name}({user_id}) 是管理员/群主，免疫中弹"
                    )
                    yield event.plain_result(
                        f"💥 枪声炸响！\n😱 {user_name} 中弹倒地！\n⚠️ 管理员/群主免疫！"
                    )
                else:
                    if self.stuck_probability > random.random():
                        trigger_msg = text_manager.get_text("trigger_descriptions")
                        reaction_msg = text_manager.get_text(
                            "user_reactions", sender_nickname=user_name
                        )
                        yield event.plain_result(
                            f"💥 {trigger_msg}\n😱 {reaction_msg}\n子弹卡壳了！真是个幸运儿！"
                        )
                    else:
                        # 普通用户，执行禁言
                        ban_duration = await self._ban_user(event, user_id)
                        if ban_duration > 0:
                            formatted_duration = self._format_ban_duration(ban_duration)
                            ban_msg = f"🔇 禁言 {formatted_duration}"
                        else:
                            ban_msg = "⚠️ 禁言失败！"

                        logger.info(f"💥 用户 {user_name}({user_id}) 在群 {group_id} 中弹")

                        # 使用YAML文本
                        trigger_msg = text_manager.get_text("trigger_descriptions")
                        reaction_msg = text_manager.get_text(
                            "user_reactions", sender_nickname=user_name
                        )
                        yield event.plain_result(
                            f"💥 {trigger_msg}\n😱 {reaction_msg}\n{ban_msg}"
                        )
            else:
                # 空弹
                game["current"] = (current + 1) % len(chambers)

                logger.info(f"用户 {user_name}({user_id}) 在群 {group_id} 空弹逃生")

                # 使用YAML文本
                miss_msg = text_manager.get_text(
                    "miss_messages", sender_nickname=user_name
                )
                yield event.plain_result(miss_msg)

            # 检查游戏结束条件
            if self._check_game_end(game):
                self._cleanup_game(group_id)
                logger.info(f"群 {group_id} 游戏结束")
                end_msg = text_manager.get_text("game_end")
                yield event.plain_result(f"🏁 {end_msg}\n🔄 再来一局？")

        except Exception as e:
            logger.error(f"开枪失败: {e}")
            yield event.plain_result("❌ 操作失败，请重试")

    @filter.command_group("左轮")
    def revolver_group(self):
        """左轮手枪游戏指令组"""
        pass

    @revolver_group.command("状态")
    async def game_status(self, event: AstrMessageEvent):
        """查看游戏状态

        用法: [指令前缀]左轮 状态
        查看当前游戏的子弹剩余情况和弹膛状态
        """
        try:
            group_id = self._get_group_id(event)
            if not group_id:
                yield event.plain_result("❌ 仅限群聊使用")
                return

            game = self.group_games.get(group_id)
            if not game:
                yield event.plain_result(
                    "🔍 没有游戏进行中\n💡 使用 /装填 开始游戏（随机装填）\n💡 管理员可使用 /装填 [数量] 指定子弹"
                )
                return

            chambers = game["chambers"]
            current = game["current"]
            remaining = sum(chambers)

            status = "🎯 有子弹" if chambers[current] else "🍀 安全"

            yield event.plain_result(
                f"🔫 游戏进行中\n"
                f"📊 剩余子弹：{remaining}发\n"
                f"🎯 当前弹膛：第{current + 1}膛\n"
                f"{status}"
            )
        except Exception as e:
            logger.error(f"查询游戏状态失败: {e}")
            yield event.plain_result("❌ 查询失败，请重试")

    @revolver_group.command("帮助")
    async def show_help(self, event: AstrMessageEvent):
        """显示帮助信息

        用法: [指令前缀]左轮 帮助
        显示插件的使用说明和游戏规则
        """
        try:
            help_text = """🔫 左轮手枪对决 v1.0

【用户指令】
/装填 - 随机装填子弹（1-6发）
/开枪 - 扣动扳机
/左轮 状态 - 查看游戏状态
/左轮 帮助 - 显示帮助

【管理员指令】
/装填 [数量] - 装填指定数量子弹（1-6发）
/走火开 - 开启随机走火
/走火关 - 关闭随机走火

【AI功能】
• "来玩左轮手枪" - 开启游戏
• "我也要玩" - 参与游戏
• "游戏状态" - 查询状态

【游戏规则】
• 6弹膛，随机装填指定数量子弹
• 中弹禁言60-300秒随机时长
• 超时120秒自动结束游戏
• 走火概率0.3%(如开启)
• 支持自然语言交互"""

            yield event.plain_result(help_text)
        except Exception as e:
            logger.error(f"显示帮助失败: {e}")
            yield event.plain_result("❌ 显示帮助失败")

    @filter.command("走火开")
    async def enable_misfire(self, event: AstrMessageEvent):
        """开启随机走火

        用法: [指令前缀]走火开
        开启后群聊中每条消息都有概率触发随机走火
        """
        try:
            group_id = self._get_group_id(event)
            if not group_id:
                yield event.plain_result("❌ 仅限群聊使用")
                return

            # 检查群管理员权限
            if not await self._is_group_admin(event):
                user_name = self._get_user_name(event)
                yield event.plain_result(f"😏 {user_name}，你又不是管理才不听你的！")
                return

            self._init_group(group_id)
            self.group_misfire[group_id] = True
            self._save_misfire_config()
            logger.info(f"群 {group_id} 随机走火已开启")
            yield event.plain_result("🔥 随机走火已开启！")
        except Exception as e:
            logger.error(f"开启走火失败: {e}")
            yield event.plain_result("❌ 操作失败，请重试")

    @filter.command("走火关")
    async def disable_misfire(self, event: AstrMessageEvent):
        """关闭随机走火

        用法: [指令前缀]走火关
        关闭随机走火功能
        """
        try:
            group_id = self._get_group_id(event)
            if not group_id:
                yield event.plain_result("❌ 仅限群聊使用")
                return

            # 检查群管理员权限
            if not await self._is_group_admin(event):
                user_name = self._get_user_name(event)
                yield event.plain_result(f"😏 {user_name}，你又不是管理才不听你的！")
                return

            self._init_group(group_id)
            self.group_misfire[group_id] = False
            self._save_misfire_config()
            logger.info(f"群 {group_id} 随机走火已关闭")
            yield event.plain_result("💤 随机走火已关闭！")
        except Exception as e:
            logger.error(f"关闭走火失败: {e}")
            yield event.plain_result("❌ 操作失败，请重试")

    @filter.command("结束游戏")
    async def end_game(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        if not group_id:
            yield event.plain_result("❌ 仅限群聊使用")
            return
        self._cleanup_game(group_id)
        logger.info(f"AI: 群 {group_id} 游戏结束")
        end_msg = text_manager.get_text("game_end")
        yield event.plain_result(f"🏁 {end_msg}\n🔄 再来一局？")

    # ========== 随机走火监听 ==========

    @filter.event_message_type(
        EventMessageType.GROUP_MESSAGE if EventMessageType else "group"
    )
    async def on_group_message(self, event: AstrMessageEvent):
        """监听群消息，触发随机走火

        监听非指令消息，根据设定的概率触发随机走火事件
        """
        try:
            # 检查走火（不检查前缀，依赖框架指令系统处理指令）
            group_id = self._get_group_id(event)
            if group_id and self._check_misfire(group_id):
                user_name = self._get_user_name(event)
                user_id = int(event.get_sender_id())

                # 检查是否可禁言（管理员/群主免疫）
                if not await self._is_user_bannable(event, user_id):
                    # 管理员/群主免疫，直接显示免疫提示
                    logger.info(
                        f"⏭️ 群 {group_id} 用户 {user_name}({user_id}) 是管理员/群主，免疫随机走火"
                    )
                    yield event.plain_result(
                        f"💥 手枪走火！\n😱 {user_name} 不幸中弹！\n⚠️ 管理员/群主免疫！"
                    )
                else:
                    # 普通用户，执行禁言
                    ban_duration = await self._ban_user(event, user_id)
                    if ban_duration > 0:
                        formatted_duration = self._format_ban_duration(ban_duration)
                        ban_msg = f"🔇 禁言 {formatted_duration}！"
                    else:
                        ban_msg = "⚠️ 禁言失败！"

                    logger.info(
                        f"💥 群 {group_id} 用户 {user_name}({user_id}) 触发随机走火"
                    )

                    # 使用YAML文本
                    misfire_desc = text_manager.get_text("misfire_descriptions")
                    reaction_msg = text_manager.get_text(
                        "user_reactions", sender_nickname=user_name
                    )
                    yield event.plain_result(
                        f"💥 {misfire_desc}\n😱 {reaction_msg}\n{ban_msg}"
                    )
        except Exception as e:
            logger.error(f"随机走火监听失败: {e}")

    # ========== 辅助功能 ==========

    async def _start_timeout(self, event: AstrMessageEvent, group_id: int):
        """启动超时机制

        Args:
            event: 消息事件对象
            group_id: 群ID

        Note:
            使用 asyncio 创建后台任务，超时后自动结束游戏
        """
        # 取消之前的超时任务（如果存在）
        if group_id in self.timeout_tasks:
            task = self.timeout_tasks[group_id]
            if not task.done():
                task.cancel()

        # 保存必要的信息用于超时回调
        bot = event.bot

        # 创建新的超时任务
        async def timeout_check():
            try:
                await asyncio.sleep(self.timeout)
                # 检查游戏是否还在进行
                if group_id in self.group_games:
                    # 清理游戏状态
                    del self.group_games[group_id]

                    # 发送超时通知（使用bot对象）
                    try:
                        timeout_msg = text_manager.get_text("timeout")
                        if hasattr(bot, "send_group_msg"):
                            await bot.send_group_msg(
                                group_id=group_id,
                                message=f"⏰ {timeout_msg}\n⏱️ {self.timeout} 秒无人操作\n🏁 游戏已自动结束",
                            )
                    except Exception as e:
                        logger.error(f"发送超时通知失败: {e}", exc_info=True)

                    logger.info(f"群 {group_id} 游戏因超时而结束")
            except asyncio.CancelledError:
                # 任务被取消，说明有新操作
                pass
            except Exception as e:
                logger.error(f"超时检查失败: {e}", exc_info=True)

        # 启动超时任务
        self.timeout_tasks[group_id] = asyncio.create_task(timeout_check())
        logger.debug(f"群 {group_id} 超时任务已启动，{self.timeout} 秒后触发")

    # ========== AI触发器管理 ==========

    def _register_ai_trigger(self, action: str, event: AstrMessageEvent) -> str:
        """注册AI触发器等待事件

        Args:
            action: 操作类型
            event: 消息事件对象

        Returns:
            生成的唯一标识符
        """
        # 使用插件内部计数器生成一致的ID
        self.ai_trigger_counter += 1
        unique_id = f"trigger_{self.ai_trigger_counter}_{event.get_sender_id()}"

        logger.info(f"AI trigger registered: {unique_id}, action={action}")
        self.ai_trigger_queue[unique_id] = {
            "action": action,
            "event": event,
            "timestamp": datetime.datetime.now(),
        }

        return unique_id

    async def _execute_ai_trigger(self, unique_id: str):
        """执行AI触发的操作

        Args:
            unique_id: 唯一标识符
        """
        if unique_id not in self.ai_trigger_queue:
            return

        trigger_data = self.ai_trigger_queue.pop(unique_id)

        action = trigger_data["action"]
        event = trigger_data["event"]

        try:
            execution_time = datetime.datetime.now() - trigger_data["timestamp"]
            logger.info(
                f"Executing AI trigger: {unique_id}, action={action}, wait_time={execution_time.total_seconds():.1f}s"
            )

            if action == "start":
                await self.ai_start_game(event, None)
            elif action == "join":
                await self.ai_join_game(event)
            elif action == "status":
                await self.ai_check_status(event)

        except Exception as e:
            logger.error(f"AI trigger execution failed: {e}", exc_info=True)

    @filter.on_decorating_result(priority=5)
    async def _on_decorating_result(self, event: AstrMessageEvent):
        """消息装饰钩子 - 标记AI消息即将发送

        Args:
            event: 消息事件对象
        """
        try:
            # 只记录有AI触发器待处理，但不执行
            if self.ai_trigger_queue:
                logger.info(
                    f"Decorating result, {len(self.ai_trigger_queue)} triggers pending"
                )
        except Exception as e:
            logger.error(f"Decorating result hook failed: {e}", exc_info=True)

    @filter.after_message_sent(priority=10)
    async def _on_message_sent(self, event: AstrMessageEvent):
        """消息发送后钩子 - 执行待处理的AI触发器

        Args:
            event: 消息事件对象
        """
        try:
            # 执行最早的待处理触发器
            if self.ai_trigger_queue:
                # 获取最早的触发器
                oldest_id = min(
                    self.ai_trigger_queue.keys(),
                    key=lambda k: self.ai_trigger_queue[k]["timestamp"],
                )

                logger.info(f"Message sent, executing AI trigger: {oldest_id}")

                # 使用配置的延迟时间
                delay = self.ai_trigger_delay
                logger.info(f"Waiting {delay}s before executing")
                await asyncio.sleep(delay)
                await self._execute_ai_trigger(oldest_id)

        except Exception as e:
            logger.error(f"Message sent hook failed: {e}", exc_info=True)

    # ========== AI工具调用方法 ==========

    async def ai_start_game(self, event: AstrMessageEvent, bullets: int | None = None):
        """AI启动游戏 - 供AI工具调用

        Args:
            event: 消息事件对象
            bullets: 子弹数量(可选)
        """
        group_id = self._get_group_id(event)
        if not group_id:
            logger.warning("AI工具无法获取group_id")
            return

        try:
            self._init_group(group_id)
            user_name = self._get_user_name(event)

            # 检查是否已有游戏
            if group_id in self.group_games:
                await event.bot.send_group_msg(
                    group_id=group_id, message=f"💥 {user_name}，游戏还在进行中！"
                )
                return

            # 解析子弹数量
            max_allowed = (
                self.chamber_count - 1 if self.no_full_chamber else self.chamber_count
            )
            if bullets is None:
                # 未指定或无效数量，随机装填
                bullets = self._get_random_bullet_count()

            # 创建游戏
            chambers = self._create_chambers(bullets)
            self.group_games[group_id] = {
                "chambers": chambers,
                "current": 0,
                "start_time": datetime.datetime.now(),
                "shot_count": 0,  # 记录已射击次数
            }

            # 设置超时
            await self._start_timeout(event, group_id)

            logger.info(f"AI: 用户 {user_name} 在群 {group_id} 装填 {bullets} 发子弹")

            # 构建装填消息
            if self.hide_bullet_count:
                load_msg = text_manager.get_text(
                    "load_messages", sender_nickname=user_name, bullet_count="?"
                )
            else:
                load_msg = text_manager.get_text(
                    "load_messages", sender_nickname=user_name, bullet_count=bullets
                )
            response_text = f"🎯 {user_name} 挑战命运！\n🔫 {load_msg}\n💀 {self.chamber_count} 弹膛，谁敢扣动扳机？\n⚡ 限时 {self.timeout} 秒！"
            await event.bot.send_group_msg(group_id=group_id, message=response_text)

        except Exception as e:
            logger.error(f"AI启动游戏失败: {e}", exc_info=True)
            await event.bot.send_group_msg(
                group_id=group_id, message="❌ 游戏启动失败，请重试"
            )

    async def ai_join_game(self, event: AstrMessageEvent):
        """AI参与游戏 - 供AI工具调用

        Args:
            event: 消息事件对象
        """
        group_id = self._get_group_id(event)
        if not group_id:
            logger.warning("AI工具无法获取group_id")
            return

        try:
            self._init_group(group_id)
            user_name = self._get_user_name(event)
            user_id = int(event.get_sender_id())

            # 检查游戏状态
            game = self.group_games.get(group_id)
            if not game:
                await event.bot.send_group_msg(
                    group_id=group_id, message=f"⚠️ {user_name}，枪里没子弹！"
                )
                return

            # 重置超时
            await self._start_timeout(event, group_id)

            # 执行射击
            chambers = game["chambers"]
            current = game["current"]
            hit = chambers[current]
            result_msg = ""

            # 增加射击计数
            game["shot_count"] = game.get("shot_count", 0) + 1

            if hit:
                # 中弹
                chambers[current] = False
                game["current"] = (current + 1) % self.chamber_count

                # 检查是否可禁言（管理员/群主免疫）
                if not await self._is_user_bannable(event, user_id):
                    logger.info(
                        f"⏭️ AI: 用户 {user_name}({user_id}) 是管理员/群主，免疫中弹"
                    )
                    result_msg = (
                        f"💥 枪声炸响！\n😱 {user_name} 中弹倒地！\n⚠️ 管理员/群主免疫！"
                    )
                else:
                    if self.stuck_probability > random.random():
                        trigger_msg = text_manager.get_text("trigger_descriptions")
                        reaction_msg = text_manager.get_text(
                            "user_reactions", sender_nickname=user_name
                        )
                        yield event.plain_result(
                            f"💥 {trigger_msg}\n😱 {reaction_msg}\n子弹卡壳！真是个幸运儿！"
                        )
                    else:
                        # 普通用户，执行禁言
                        ban_duration = await self._ban_user(event, user_id)
                        if ban_duration > 0:
                            formatted_duration = self._format_ban_duration(ban_duration)
                            ban_msg = f"🔇 禁言 {formatted_duration}"
                        else:
                            ban_msg = "⚠️ 禁言失败！"

                        logger.info(
                            f"💥 AI: 用户 {user_name}({user_id}) 在群 {group_id} 中弹"
                        )

                        # 使用YAML文本
                        trigger_msg = text_manager.get_text("trigger_descriptions")
                        reaction_msg = text_manager.get_text(
                            "user_reactions", sender_nickname=user_name
                        )
                        result_msg = f"💥 {trigger_msg}\n😱 {reaction_msg}\n{ban_msg}"
            else:
                # 空弹
                game["current"] = (current + 1) % self.chamber_count
                logger.info(f"AI: 用户 {user_name}({user_id}) 在群 {group_id} 空弹逃生")
                # 使用YAML文本
                result_msg = text_manager.get_text(
                    "miss_messages", sender_nickname=user_name
                )

            # 发送初步结果
            await event.bot.send_group_msg(group_id=group_id, message=result_msg)

            # 检查游戏结束条件
            if self._check_game_end(game):
                self._cleanup_game(group_id)
                logger.info(f"AI: 群 {group_id} 游戏结束")
                end_msg = text_manager.get_text("game_end")
                await event.bot.send_group_msg(
                    group_id=group_id, message=f"🏁 {end_msg}\n🔄 再来一局？"
                )

        except Exception as e:
            logger.error(f"AI参与游戏失败: {e}", exc_info=True)
            await event.bot.send_group_msg(
                group_id=group_id, message="❌ 操作失败，请重试"
            )

    async def ai_check_status(self, event: AstrMessageEvent):
        """AI查询游戏状态 - 供AI工具调用

        Args:
            event: 消息事件对象
        """
        group_id = self._get_group_id(event)
        if not group_id:
            logger.warning("AI工具无法获取group_id")
            return

        try:
            game = self.group_games.get(group_id)
            if not game:
                response_text = "🔍 没有游戏进行中\n💡 使用 /装填 开始游戏（随机装填）\n💡 管理员可使用 /装填 [数量] 指定子弹"
            else:
                chambers = game["chambers"]
                current = game["current"]
                remaining = sum(chambers)
                status = "🎯 有子弹" if chambers[current] else "🍀 安全"
                response_text = (
                    f"🔫 游戏进行中\n"
                    f"📊 剩余子弹：{remaining}发\n"
                    f"🎯 当前弹膛：第{current + 1}膛\n"
                    f"{status}"
                )
            await event.bot.send_group_msg(group_id=group_id, message=response_text)
        except Exception as e:
            logger.error(f"AI查询状态失败: {e}", exc_info=True)
            await event.bot.send_group_msg(
                group_id=group_id, message="❌ 查询失败，请重试"
            )

    async def terminate(self):
        """插件卸载清理

        清理所有游戏状态和配置，确保插件安全卸载
        """
        try:
            # 先记录数量再清理
            num_games = len(self.group_games)
            num_configs = len(self.group_misfire)
            num_tasks = len(self.timeout_tasks)
            num_ai_triggers = len(self.ai_trigger_queue)

            # 取消所有超时任务
            for task in self.timeout_tasks.values():
                if not task.done():
                    task.cancel()

            # 清理游戏状态
            self.group_games.clear()
            self.group_misfire.clear()
            self.timeout_tasks.clear()
            self.ai_trigger_queue.clear()

            # 记录卸载日志
            logger.info(f"左轮手枪插件 v{self.plugin_version} 已安全卸载")
            logger.info(f"清理了 {num_games} 个游戏状态")
            logger.info(f"清理了 {num_configs} 个群配置")
            logger.info(f"取消了 {num_tasks} 个超时任务")
            logger.info(f"清理了 {num_ai_triggers} 个AI触发器")
        except Exception as e:
            logger.error(f"插件卸载失败: {e}")
            # 即使清理失败也不抛出异常，确保插件能够卸载
