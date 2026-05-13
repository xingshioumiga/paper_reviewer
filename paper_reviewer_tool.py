"""LaTeX parsing helpers: split by ``\\section``, strip duplicated headings, re-render.

将论文 TeX 按真实 \\section 命令切块、清理 LLM 重复标题并拼回全文。
"""

from langgraph_state import Section


SECTION_COMMAND = "\\section"
LABEL_COMMAND = "\\label"


def _is_escaped(tex: str, index: int) -> bool:
    """判断 index 处是否被奇数个反斜杠转义 / whether position ``index`` is escaped by an odd run of backslashes."""
    slash_count = 0
    pos = index - 1
    while pos >= 0 and tex[pos] == "\\":
        slash_count += 1
        pos -= 1
    return slash_count % 2 == 1


def _is_commented(tex: str, index: int) -> bool:
    """index 之前同一行内是否存在未转义的 %（即位于 TeX 注释中）/ true if an unescaped ``%`` starts a comment before ``index``."""
    line_start = tex.rfind("\n", 0, index) + 1
    pos = line_start
    while pos < index:
        if tex[pos] == "%" and not _is_escaped(tex, pos):
            return True
        pos += 1
    return False


def _parse_balanced(tex: str, start: int, open_char: str, close_char: str) -> int | None:
    r"""解析成对括号；支持 title 内嵌 ``\label{...}`` 等 / parse balanced delimiters; supports nested LaTeX in titles."""
    if start >= len(tex) or tex[start] != open_char:
        return None

    depth = 0
    pos = start
    while pos < len(tex):
        char = tex[pos]
        if char == open_char and not _is_escaped(tex, pos):
            depth += 1
        elif char == close_char and not _is_escaped(tex, pos):
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return None


def _parse_section_command(tex: str, start: int) -> int | None:
    r"""返回完整 ``\section`` 命令结束下标；失败返回 ``None`` / end index of full ``\section`` cmd, or ``None``."""
    if not tex.startswith(SECTION_COMMAND, start):
        return None
    if start > 0 and tex[start - 1].isalpha():
        return None

    pos = start + len(SECTION_COMMAND)
    if pos < len(tex) and tex[pos] == "*":
        pos += 1

    while pos < len(tex) and tex[pos].isspace():
        pos += 1

    if pos < len(tex) and tex[pos] == "[":
        option_end = _parse_balanced(tex, pos, "[", "]")
        if option_end is None:
            return None
        pos = option_end
        while pos < len(tex) and tex[pos].isspace():
            pos += 1

    return _parse_balanced(tex, pos, "{", "}")


def _find_section_commands(tex: str) -> list[tuple[int, int]]:
    """扫描全文，收集非注释区内真实 ``\section`` 命令的 (start, end) / scan for real ``\section`` spans outside comments."""
    commands = []
    pos = 0
    while True:
        start = tex.find(SECTION_COMMAND, pos)
        if start == -1:
            break

        end = None if _is_commented(tex, start) else _parse_section_command(tex, start)
        if end is not None:
            commands.append((start, end))
            pos = end
        else:
            pos = start + len(SECTION_COMMAND)
    return commands


def split_prefix_and_sections(tex: str) -> tuple[str, list[Section]]:
    """切分为 (前缀, 节列表)：前缀为首个 ``\\section`` 之前；无节时 ``(tex, [])`` / split into prefix and sections; empty if no ``\\section``."""
    commands = _find_section_commands(tex)
    if not commands:
        return tex, []
    prefix = tex[: commands[0][0]]
    sections: list[Section] = []
    for sec_idx, (start, end) in enumerate(commands):
        next_start = commands[sec_idx + 1][0] if sec_idx + 1 < len(commands) else len(tex)
        sections.append(
            Section(
                id=f"sec_{sec_idx}",
                title=tex[start:end],
                content=tex[end:next_start].strip(),
            )
        )
    return prefix, sections


def split_into_sections(tex: str) -> list[Section]:
    """将全文按 \\section 切成 Section 列表；每段正文直到下一节前。
    Split full TeX into sections; body runs until the next section command."""
    _, sections = split_prefix_and_sections(tex)
    return sections


# ``\\section`` 标题后若出现字面量 ``\\``+``n`` 常为 JSON 伪影，勿与 ``\\neq`` 等混淆 / two-char ``\\n`` after titles is often JSON leakage, not ``\\neq``.
_PROTECTED_AFTER_BACKSLASH_N = (
    "abla",
    "eq",
    "eg",
    "u",
    "ot",
    "ewline",
    "ewpage",
    "ewcommand",
    "ewenvironment",
    "ewtheorem",
    "oindent",
    "ocite",
    "olimits",
    "onumber",
    "oalign",
    "obreak",
    "ormalsize",
    "otag",
    "otin",
    "parallel",
    "oexpand",
    "ouppercase",
    "olowercase",
)


def normalize_fake_newlines_in_latex(s: str) -> str:
    r"""将 JSON 中误写的两字符 ``\``+``n`` 转为真实换行，且保留 ``\neq``、``\nabla`` 等合法命令 / turn spurious two-char ``\``+``n`` into real newlines without eating ``\neq``, ``\nabla``, …"""
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if i + 1 < n and s[i] == "\\" and s[i + 1] == "n":
            tail = s[i + 2 : i + 2 + 32]
            if any(tail.startswith(p) for p in _PROTECTED_AFTER_BACKSLASH_N):
                out.append("\\n")
                i += 2
                continue
            out.append("\n")
            i += 2
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def strip_leading_section_command(content: str) -> str:
    """去掉正文开头误重复的 \\section 标题行（及紧随 label）/ strip duplicate leading ``\\section`` (and following ``\\label``) from body."""
    leading_len = len(content) - len(content.lstrip())
    start = leading_len
    end = _parse_section_command(content, start)
    if end is None:
        return content.strip()

    remainder = content[end:].strip()
    while remainder.startswith(LABEL_COMMAND):
        pos = len(LABEL_COMMAND)
        while pos < len(remainder) and remainder[pos].isspace():
            pos += 1
        label_end = _parse_balanced(remainder, pos, "{", "}")
        if label_end is None:
            break
        remainder = remainder[label_end:].strip()
    return remainder


def render_sections(sections: list[Section]) -> str:
    """将 Section 列表拼回单一 TeX；去掉正文中误重复的 \\section。
    Join sections into one TeX string; strip stray leading section commands in bodies."""
    return "\n\n".join(
        f"{section.title}\n{strip_leading_section_command(section.content)}"
        for section in sections
    )


def assemble_output_tex(
    document_prefix: str,
    best_tex: str,
    current_tex: str,
    sections: list[Section],
) -> str:
    """写盘用全文：前缀 + 渲染后的正文（``best_tex`` 或 ``current_tex``）/ full document for disk: prefix + rendered bodies."""
    body = best_tex or current_tex
    if not body and sections:
        body = render_sections(sections)
    return document_prefix + body
