from langgraph_state import Section


SECTION_COMMAND = "\\section"
LABEL_COMMAND = "\\label"


def _is_escaped(tex: str, index: int) -> bool:
    slash_count = 0
    pos = index - 1
    while pos >= 0 and tex[pos] == "\\":
        slash_count += 1
        pos -= 1
    return slash_count % 2 == 1


def _is_commented(tex: str, index: int) -> bool:
    line_start = tex.rfind("\n", 0, index) + 1
    pos = line_start
    while pos < index:
        if tex[pos] == "%" and not _is_escaped(tex, pos):
            return True
        pos += 1
    return False


def _parse_balanced(tex: str, start: int, open_char: str, close_char: str) -> int | None:
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


def split_into_sections(tex: str) -> list[Section]:
    commands = _find_section_commands(tex)
    sections = []

    for sec_idx, (start, end) in enumerate(commands):
        next_start = commands[sec_idx + 1][0] if sec_idx + 1 < len(commands) else len(tex)
        sections.append(
            Section(
                id=f"sec_{sec_idx}",
                title=tex[start:end],
                content=tex[end:next_start].strip(),
            )
        )

    return sections


def strip_leading_section_command(content: str) -> str:
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
    return "\n\n".join(
        f"{section.title}\n{strip_leading_section_command(section.content)}"
        for section in sections
    )
