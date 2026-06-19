"""
规则数据结构定义 — 清单规范 + 定额
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BOQItemRule:
    """清单规范中的一条规则"""
    code: str                        # 9位编码 如 010502001
    name: str                        # 项目名称
    required_features: list[str]     # 必填项目特征
    unit: str                        # 计量单位
    calc_rule: str                   # 计算规则
    work_content: list[str]          # 工作内容
    section: str                     # 所属分部 如 "E.2 现浇混凝土柱"
    cross_refs: list[str] = field(default_factory=list)  # 跨分部依赖的编码
    notes: list[str] = field(default_factory=list)


@dataclass
class QuotaItem:
    """定额子目"""
    code: str                        # 定额编号 如 "AD0001"
    name: str                        # 定额名称
    unit: str                        # 计量单位（如 10m³）
    labor: dict[str, float]          # 人工消耗 {工种: 工日}
    materials: dict[str, float]      # 材料消耗 {材料名: 数量}
    machinery: dict[str, float]      # 机械消耗 {机械名: 台班}
    applicable_boq_codes: list[str]  # 适用的清单编码
    section: str                     # 所属章节


@dataclass
class DependencyRule:
    """依赖规则：if_has X → must_have Y"""
    if_has: str                      # 如果清单中有这个编码
    must_have: str                   # 那必须有这个编码
    reason: str                      # 原因
    severity: str                    # "error" | "warning" | "info"
    category: str                    # "cross_section" | "same_section" | "quota"


@dataclass
class CheckResult:
    """单条检查结果"""
    category: str                    # 漏项 / 列错 / 算错 / 定额套错
    severity: str                    # error / warning / info
    row: Optional[int]               # BOQ 中的行号
    code: str                        # 涉及的项目编码
    message: str                     # 描述
    suggestion: str                  # 修改建议
