import re
from typing import List

from langgraph_state import Section


def split_into_sections(tex: str) -> List[Section]:
    pattern = r"(\\section\{.*?\})"
    parts = re.split(pattern, tex)

    sections = []
    for i in range(1, len(parts), 2):
        title = parts[i]
        content = parts[i+1] if i+1 < len(parts) else ""
        sections.append(Section(
            id=f"sec_{i}",
            title=title,
            content=content.strip()
        ))
    return sections