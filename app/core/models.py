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
    has_deficiency: int  # スキル欠け（マイナス値のスキルを含む）の有無。0=無, 1=有
    print_resistance: int
    skills: list[ParsedSkill] = field(default_factory=list)
