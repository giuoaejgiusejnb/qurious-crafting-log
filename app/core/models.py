from dataclasses import dataclass, field


@dataclass
class ParsedSkill:
    name: str
    value: int


@dataclass
class ParsedResult:
    zeny_count: int
    zeny: int
    slot_add: int
    total_cost: int
    print_minus: int
    print_resistance: int
    skills: list[ParsedSkill] = field(default_factory=list)
