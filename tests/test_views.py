"""views 序列化测试。"""

from __future__ import annotations

import types

from kurigram_mcp.telegram.views import (
    inline_result_view,
    markup_view,
    message_view,
    poll_view,
)


def make_msg(**overrides) -> types.SimpleNamespace:
    base = {
        "id": 42,
        "chat": types.SimpleNamespace(id=6540476263),
        "date": None,
        "edit_date": None,
        "out": True,
        "from_user": None,
        "text": "hello",
        "caption": None,
        "media": None,
        "media_group_id": None,
        "poll": None,
        "reply_to_message_id": None,
        "service": None,
        "reply_markup": None,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_message_view_plain() -> None:
    v = message_view(make_msg())
    assert v["message_id"] == 42
    assert v["chat_id"] == 6540476263
    assert v["text"] == "hello"
    assert v["from"] is None
    assert v["media"] is None
    assert v["rich"] is None  # 无富消息


def _rich_text(t: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(text=t)


def test_rich_text_rendering() -> None:
    """RichText 树递归渲染:TextConcat/样式/URL。"""
    from kurigram_mcp.telegram.views import _rich_text

    # TextConcat 直接拼
    assert _rich_text(types.SimpleNamespace(texts=[_rich_text("a"), _rich_text("b")])) == "ab"
    # 样式包装递归(TextItalic 形态:text 是 RichText 对象)
    assert _rich_text(types.SimpleNamespace(text=_rich_text("x"))) == "x"
    # TextUrl:text + url(&amp; 反转义)
    url = types.SimpleNamespace(text=_rich_text("WIKI"), url="https://example.com&amp;x=1")
    assert _rich_text(url) == "WIKI (https://example.com&x=1)"
    # TextPlain
    assert _rich_text(_rich_text("plain")) == "plain"
    # None 安全
    assert _rich_text(None) == ""


def test_rich_message_view_extracts_blocks() -> None:
    """guest bot 富消息:blocks → {text, blocks}。"""
    from kurigram_mcp.telegram.views import _rich_message_view

    rich = types.SimpleNamespace(
        blocks=[
            types.SimpleNamespace(
                text=types.SimpleNamespace(texts=[_rich_text("你好！🌟 "), _rich_text("有什么想试试的？")])
            ),
            types.SimpleNamespace(
                text=types.SimpleNamespace(
                    text=types.SimpleNamespace(
                        texts=[
                            _rich_text("No chat history. "),
                            types.SimpleNamespace(
                                text=_rich_text("Add me to the chat"),
                                url="https://t.me/mira?x=1&amp;y=2",
                            ),
                        ]
                    )
                )
            ),
        ]
    )
    v = _rich_message_view(types.SimpleNamespace(rich_message=rich))
    assert v is not None
    assert v["text"] == "你好！🌟 有什么想试试的？\nNo chat history. Add me to the chat (https://t.me/mira?x=1&y=2)"
    assert len(v["blocks"]) == 2
    # 无 rich_message → None
    assert _rich_message_view(types.SimpleNamespace(rich_message=None)) is None


def test_message_view_with_rich() -> None:
    """message_view 透出 rich 字段。"""
    rich = types.SimpleNamespace(
        blocks=[types.SimpleNamespace(text=types.SimpleNamespace(texts=[_rich_text("AI 内容")]))]
    )
    msg = make_msg(text=None)
    msg.raw = types.SimpleNamespace(rich_message=rich)
    v = message_view(msg)
    assert v["text"] is None  # 普通文本为空
    assert v["rich"]["text"] == "AI 内容"


def test_message_view_with_sender_and_media() -> None:
    msg = make_msg(
        from_user=types.SimpleNamespace(id=1, username="zl_ing", first_name="zio", is_bot=False),
        media=types.SimpleNamespace(value="PHOTO"),
        text=None,
        caption="cap",
    )
    v = message_view(msg)
    assert v["text"] == "cap"
    assert v["media"] == "PHOTO"
    assert v["from"]["username"] == "zl_ing"
    assert v["from"]["is_bot"] is False


def test_message_view_bot_sender() -> None:
    msg = make_msg(
        from_user=types.SimpleNamespace(id=6540476263, username="GLBetabot", first_name="GL Beta", is_bot=True)
    )
    assert msg and message_view(msg)["from"]["is_bot"] is True


def test_markup_view_inline() -> None:
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("点我", callback_data=b"btn_1"),
                InlineKeyboardButton("官网", url="https://x.com"),
            ],
            [InlineKeyboardButton("下一行", callback_data=b"btn_2")],
        ]
    )
    v = markup_view(markup)
    assert v["type"] == "inline"
    assert v["rows"][0][0] == {"text": "点我", "callback_data": "btn_1"}
    assert v["rows"][0][1] == {"text": "官网", "url": "https://x.com"}
    assert v["rows"][1][0]["callback_data"] == "btn_2"


def test_markup_view_reply_keyboard() -> None:
    from pyrogram.types import KeyboardButton, ReplyKeyboardMarkup

    markup = ReplyKeyboardMarkup([[KeyboardButton("帮助")]])
    v = markup_view(markup)
    assert v["type"] == "reply"
    assert v["rows"] == [[{"text": "帮助"}]]


def test_markup_view_none() -> None:
    assert markup_view(None) is None


def test_message_view_media_group_and_poll() -> None:
    """相册消息应带 media_group_id;投票消息应带 poll 摘要。"""
    poll = types.SimpleNamespace(
        id="5959268912454516736",
        question="今天吃啥?",
        options=[
            types.SimpleNamespace(text="火锅", voter_count=3, data=b"0"),
            types.SimpleNamespace(text="烧烤", voter_count=1, data=b"1"),
        ],
        total_voters=4,
        is_closed=False,
        is_anonymous=True,
        type=types.SimpleNamespace(value="REGULAR"),
    )
    msg = make_msg(media_group_id=777777, poll=poll, text=None)
    v = message_view(msg)
    assert v["media_group_id"] == 777777
    assert v["poll"]["question"] == "今天吃啥?"
    assert v["poll"]["options"] == [
        {"text": "火锅", "voters": 3, "data": b"0"},
        {"text": "烧烤", "voters": 1, "data": b"1"},
    ]
    assert v["poll"]["total_voters"] == 4
    assert v["poll"]["type"] == "REGULAR"


def test_poll_view_voter_count_fallback() -> None:
    """kurigram 新版属性是 voter_count;旧版 voters 应兜底,不能恒为 0。"""
    import datetime

    from kurigram_mcp.telegram.views import poll_view

    # 新版:voter_count
    poll = types.SimpleNamespace(
        id="1",
        question="q",
        options=[types.SimpleNamespace(text="A", voter_count=5, data=None)],
        total_voters=5,
        is_closed=False,
        is_anonymous=True,
        type=types.SimpleNamespace(value="REGULAR"),
    )
    assert poll_view(poll)["options"][0]["voters"] == 5
    # 旧版兜底:voters
    poll2 = types.SimpleNamespace(
        id="2",
        question="q",
        options=[types.SimpleNamespace(text="A", voters=2, data=None)],
        total_voters=2,
        is_closed=False,
        is_anonymous=True,
        type=types.SimpleNamespace(value="REGULAR"),
    )
    assert poll_view(poll2)["options"][0]["voters"] == 2
    # 都没有 -> 0
    poll3 = types.SimpleNamespace(
        id="3",
        question="q",
        options=[types.SimpleNamespace(text="A", data=None)],
        total_voters=0,
        is_closed=False,
        is_anonymous=True,
        type=types.SimpleNamespace(value="REGULAR"),
    )
    assert poll_view(poll3)["options"][0]["voters"] == 0
    assert datetime is not None


def test_message_view_no_poll() -> None:
    assert message_view(make_msg())["poll"] is None


def test_message_view_outgoing_alias_and_utc_suffix() -> None:
    """out 应有 is_outgoing 别名;naive UTC 日期应补 Z 后缀。"""
    import datetime

    msg = make_msg(
        out=True,
        date=datetime.datetime(2026, 8, 20, 11, 4, 19, tzinfo=datetime.UTC).replace(tzinfo=None),  # naive UTC
        edit_date=datetime.datetime(2026, 8, 20, 11, 5, 0, tzinfo=datetime.UTC),
    )
    v = message_view(msg)
    assert v["out"] is True and v["is_outgoing"] is True
    assert v["date"] == "2026-08-20T11:04:19Z"
    assert v["edit_date"] == "2026-08-20T11:05:00+00:00"
    # 无日期 -> None,不崩
    assert message_view(make_msg())["date"] is None


def test_poll_view_none() -> None:
    assert poll_view(None) is None


def test_message_view_entities_summary() -> None:
    """实体摘要:bold/custom_emoji 等非 url 实体也应可见(验证格式是否生效/被降级)。"""
    msg = make_msg(text="粗体内容")
    msg.entities = [
        types.SimpleNamespace(type="bold", offset=0, length=2, url=None),
        types.SimpleNamespace(type="custom_emoji", offset=0, length=2, url=None),
    ]
    v = message_view(msg)
    assert v["entities"] == [
        {"type": "bold", "text": "粗体"},
        {"type": "custom_emoji", "text": "粗体"},
    ]
    # 无实体 -> None
    assert message_view(make_msg())["entities"] is None


def test_message_view_links() -> None:
    """子会话实测场景:bot 回复 "WIKI" 实际是超链接——视图应暴露 links。"""
    entity = types.SimpleNamespace(type="url", offset=9, length=4, url="https://wiki.getletbot.com/")
    msg = make_msg(text="Bot使用文档: WIKI", caption=None)
    msg.entities = [entity]
    v = message_view(msg)
    assert v["links"] == [{"text": "WIKI", "url": "https://wiki.getletbot.com/", "type": "url"}]
    # 无实体 -> None,不崩
    msg2 = make_msg(text="没有链接")
    msg2.entities = None
    assert message_view(msg2)["links"] is None
    # 无 url 的实体(如 bold)不输出
    msg3 = make_msg(text="加粗")
    msg3.entities = [types.SimpleNamespace(type="bold", offset=0, length=2, url=None)]
    assert message_view(msg3)["links"] is None


def test_inline_result_view() -> None:
    """内联查询结果序列化:标题/描述/URL/缩略图/消息内容。"""
    result = types.SimpleNamespace(
        id="r1",
        type="article",
        title="结果一",
        description="说明",
        url="https://example.com/1",
        thumb=types.SimpleNamespace(url="https://example.com/thumb.png"),
        send_message=types.SimpleNamespace(message="点我发送这条消息"),
    )
    v = inline_result_view(result)
    assert v == {
        "id": "r1",
        "type": "article",
        "title": "结果一",
        "description": "说明",
        "url": "https://example.com/1",
        "thumb_url": "https://example.com/thumb.png",
        "message": "点我发送这条消息",
    }
    # 无缩略图/无消息内容的媒体结果也不应崩
    media = types.SimpleNamespace(
        id="r2", type="photo", title=None, description=None, url=None, thumb=None, send_message=None
    )
    assert inline_result_view(media)["thumb_url"] is None


# ---------- 富消息(rich_message)完整结构 ----------
#
# 以下用真实 raw.types:dispatch 按类名走,SimpleNamespace 替身不适用。


def _raw_rich(blocks: list, **kw):
    from pyrogram.raw.types import RichMessage

    return types.SimpleNamespace(rich_message=RichMessage(blocks=blocks, photos=[], documents=[], **kw))


def test_rich_details_block() -> None:
    """PageBlockDetails 嵌套块不丢(旧实现只认 .text → rich: null 的报障场景)。"""
    from pyrogram.raw.types import PageBlockDetails, PageBlockParagraph, TextPlain

    from kurigram_mcp.telegram.views import _rich_message_view

    rich = _raw_rich(
        [
            PageBlockDetails(
                title=TextPlain(text="T"),
                blocks=[PageBlockParagraph(text=TextPlain(text="inner"))],
            )
        ]
    )
    v = _rich_message_view(rich)
    assert v is not None
    b = v["blocks"][0]
    assert b["type"] == "details"
    assert b["title"] == "T"
    assert b["open"] is False
    assert b["blocks"][0]["type"] == "paragraph" and b["blocks"][0]["text"] == "inner"
    assert "T" in v["text"] and "inner" in v["text"]
    assert v["buttons"] is None and v["partial"] is False


def test_rich_list_with_blocks_items() -> None:
    """PageListItemBlocks 的文本在 .blocks 里(旧实现读 .text → 列表全空的报障场景)。"""
    from pyrogram.raw.types import (
        PageBlockList,
        PageBlockParagraph,
        PageListItemBlocks,
        PageListItemText,
        TextPlain,
    )

    from kurigram_mcp.telegram.views import _rich_message_view

    rich = _raw_rich(
        [
            PageBlockList(
                items=[
                    PageListItemBlocks(blocks=[PageBlockParagraph(text=TextPlain(text="a"))]),
                    PageListItemText(text=TextPlain(text="b"), checkbox=True, checked=True),
                ]
            )
        ]
    )
    v = _rich_message_view(rich)
    b = v["blocks"][0]
    assert b["type"] == "list"
    assert [i["label"] for i in b["items"]] == ["•", "•"]
    assert b["items"][0]["text"] == "a" and "checked" not in b["items"][0]
    assert b["items"][1]["text"] == "b" and b["items"][1]["checked"] is True
    assert b["text"] == "• a\n• [x] b"
    assert v["text"] == "• a\n• [x] b"


def test_rich_ordered_list() -> None:
    from pyrogram.raw.types import PageBlockOrderedList, PageListOrderedItemText, TextPlain

    from kurigram_mcp.telegram.views import _rich_message_view

    rich = _raw_rich([PageBlockOrderedList(items=[PageListOrderedItemText(num="1.", text=TextPlain(text="x"))])])
    b = _rich_message_view(rich)["blocks"][0]
    assert b["type"] == "orderedlist"
    assert b["items"][0]["label"] == "1." and b["items"][0]["text"] == "x"
    assert b["text"] == "1. x"


def test_rich_button_row_nested_in_details() -> None:
    """嵌在 Details 里的按钮行也要出现在 rich.buttons(供 click_inline_button 点击)。"""
    from pyrogram.raw.types import (
        InlineButtonTypeCallback,
        InlineButtonTypeCopy,
        InlineButtonTypeUrl,
        PageBlockButtonRow,
        PageBlockDetails,
        PageButton,
        RichButtonStyle,
        TextPlain,
    )

    from kurigram_mcp.telegram.views import _rich_message_view

    row = PageBlockButtonRow(
        buttons=[
            PageButton(
                text=TextPlain(text="OK"),
                type=InlineButtonTypeCallback(data=b"act:1"),
                style=RichButtonStyle(bg_danger=True),
            ),
            PageButton(text=TextPlain(text="Docs"), type=InlineButtonTypeUrl(url="https://d")),
            PageButton(text=TextPlain(text="Copy"), type=InlineButtonTypeCopy(copy_text="c")),
        ]
    )
    v = _rich_message_view(_raw_rich([PageBlockDetails(title=TextPlain(text="t"), blocks=[row])]))
    assert v["buttons"] == [
        [
            {"text": "OK", "type": "callback", "callback_data": "act:1", "style": "danger"},
            {"text": "Docs", "type": "url", "url": "https://d"},
            {"text": "Copy", "type": "copy", "copy_text": "c"},
        ]
    ]
    row_block = v["blocks"][0]["blocks"][0]
    assert row_block["type"] == "buttonrow" and row_block["text"] == "[OK] [Docs] [Copy]"


def test_rich_photo_block() -> None:
    """photo_id 是 64 位整数,序列化成字符串避免 JS 丢精度。"""
    from pyrogram.raw.types import PageBlockPhoto, PageCaption, TextEmpty, TextPlain

    from kurigram_mcp.telegram.views import _rich_message_view

    rich = _raw_rich(
        [
            PageBlockPhoto(
                photo_id=2**62,
                caption=PageCaption(text=TextPlain(text="cap"), credit=TextEmpty()),
            )
        ]
    )
    b = _rich_message_view(rich)["blocks"][0]
    assert b["type"] == "photo" and b["photo_id"] == str(2**62)
    assert b["caption"] == "cap" and b["text"] == "[图片] cap"


def test_rich_unknown_block_not_dropped() -> None:
    """未知 PageBlock 类型走兜底:能递归出嵌套内容,绝不静默丢弃。"""
    from pyrogram.raw.types import PageBlockParagraph, TextPlain

    from kurigram_mcp.telegram.views import _rich_message_view

    class PageBlockWeird:
        def __init__(self) -> None:
            self.blocks = [PageBlockParagraph(text=TextPlain(text="deep"))]

    class PageBlockMystery:
        pass

    v = _rich_message_view(_raw_rich([PageBlockWeird(), PageBlockMystery()]))
    assert v["blocks"][0]["type"] == "weird" and v["blocks"][0]["text"] == "deep"
    assert v["blocks"][1]["unsupported"] is True
    assert v["text"] == "deep"


def test_rich_text_custom_emoji_and_math() -> None:
    from pyrogram.raw.types import TextCustomEmoji, TextMath

    from kurigram_mcp.telegram.views import _rich_text

    assert _rich_text(TextCustomEmoji(document_id=1, alt="🎉")) == "🎉"
    assert _rich_text(TextCustomEmoji(document_id=1, alt="")) == "[emoji]"
    assert _rich_text(TextMath(source="x^2")) == "x^2"


def test_button_view_extra_fields() -> None:
    """InlineKeyboardButton 新增字段:requires_password/copy_text/style 等。"""
    from kurigram_mcp.telegram.views import _button_view

    btn = types.SimpleNamespace(
        text="危险",
        callback_data=b"d",
        requires_password=True,
        copy_text=types.SimpleNamespace(text="复制我"),
        style=types.SimpleNamespace(name="DANGER"),
    )
    v = _button_view(btn)
    assert v["callback_data"] == "d"
    assert v["requires_password"] is True
    assert v["copy_text"] == "复制我"
    assert v["style"] == "danger"
    # DEFAULT 样式不输出
    btn2 = types.SimpleNamespace(text="普通", callback_data=b"d", style=types.SimpleNamespace(name="DEFAULT"))
    assert "style" not in _button_view(btn2)


def test_message_view_ephemeral_message_id() -> None:
    """临时消息 id=0,真实 id 在 ephemeral_message_id。"""
    msg = make_msg(id=0)
    msg.ephemeral_message_id = 777
    v = message_view(msg)
    assert v["message_id"] == 0 and v["ephemeral_message_id"] == 777
    # 普通消息 -> None
    assert message_view(make_msg())["ephemeral_message_id"] is None
