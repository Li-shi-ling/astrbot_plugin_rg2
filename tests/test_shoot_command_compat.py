from types import SimpleNamespace
from pathlib import Path
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from main import RevolverGunPlugin


def make_plugin():
    return RevolverGunPlugin.__new__(RevolverGunPlugin)


def make_event(message: str, *, triggered: bool):
    return SimpleNamespace(
        message_str=message,
        is_at_or_wake_command=triggered,
    )


def test_flexible_shoot_requires_at_or_wake_command():
    plugin = make_plugin()
    event = make_event("普通聊天里说开枪不会触发", triggered=False)

    assert plugin._is_flexible_shoot_message(event) is False


def test_flexible_shoot_accepts_triggered_message_with_punctuation():
    plugin = make_plugin()
    event = make_event("@bot 开枪!!!", triggered=True)

    assert plugin._is_flexible_shoot_message(event) is True


def test_flexible_shoot_ignores_triggered_message_without_keyword():
    plugin = make_plugin()
    event = make_event("@bot 查询状态", triggered=True)

    assert plugin._is_flexible_shoot_message(event) is False
