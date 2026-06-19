"""
规则引擎 — 对照 BOQ 与规范/定额，输出检查报告
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from rules.schema import (
    BOQItemRule, QuotaItem, DependencyRule, CheckResult
)
from collections import defaultdict


class RuleEngine:
    """检查引擎"""

    def __init__(self):
        self.boq_rules: dict[str, BOQItemRule] = {}      # code → rule
        self.quota_items: dict[str, QuotaItem] = {}       # code → quota
        self.dependency_rules: list[DependencyRule] = []
        self.sections: dict[str, list[str]] = defaultdict(list)  # section → [codes]

    # ==========================================
    # 数据加载
    # ==========================================

    def add_boq_rule(self, rule: BOQItemRule):
        self.boq_rules[rule.code] = rule
        self.sections[rule.section].append(rule.code)

    def add_quota_item(self, item: QuotaItem):
        self.quota_items[item.code] = item

    def add_dependency(self, rule: DependencyRule):
        self.dependency_rules.append(rule)

    # ==========================================
    # 检查方法
    # ==========================================

    def check(self, user_items: list[dict]) -> list[CheckResult]:
        """主入口：全部检查"""
        results = []
        results.extend(self._check_format(user_items))
        results.extend(self._check_missing_features(user_items))
        results.extend(self._check_wrong_units(user_items))
        results.extend(self._check_dependencies(user_items))
        results.extend(self._check_section_completeness(user_items))
        return results

    def check_format(self, user_items: list[dict]) -> list[CheckResult]:
        return self._check_format(user_items)

    def check_features(self, user_items: list[dict]) -> list[CheckResult]:
        return self._check_missing_features(user_items)

    def check_units(self, user_items: list[dict]) -> list[CheckResult]:
        return self._check_wrong_units(user_items)

    def check_dependencies(self, user_items: list[dict]) -> list[CheckResult]:
        return self._check_dependencies(user_items)

    def _check_format(self, items: list[dict]) -> list[CheckResult]:
        """L0: 检查编码、名称等基本字段是否缺失"""
        results = []
        for item in items:
            row = item.get("row", "")
            code = item.get("code", "").strip()
            name = item.get("name", "").strip()

            if not code:
                results.append(CheckResult(
                    category="格式错误", severity="error", row=row, code="(空)",
                    message=f"缺少项目编码",
                    suggestion="补充12位项目编码"
                ))
            elif not re.match(r"^\d{9,12}$", code):
                results.append(CheckResult(
                    category="格式错误", severity="error", row=row, code=code,
                    message=f"编码格式错（应为9-12位数字）",
                    suggestion="检查编码位数"
                ))

            if not name:
                results.append(CheckResult(
                    category="格式错误", severity="error", row=row, code=code or "(空)",
                    message=f"缺少项目名称",
                    suggestion="补充项目名称"
                ))

            if not item.get("unit", "").strip():
                results.append(CheckResult(
                    category="格式错误", severity="warning", row=row, code=code or "(空)",
                    message=f"缺少计量单位",
                    suggestion="补充计量单位"
                ))
        return results

    def _check_missing_features(self, items: list[dict]) -> list[CheckResult]:
        """检查漏填：项目特征为空或不全"""
        results = []
        for item in items:
            code_9 = item["code"][:9]  # 只取前 9 位标准编码
            rule = self.boq_rules.get(code_9)
            if not rule or not rule.required_features:
                continue

            features_text = item.get("features", "").strip()
            if not features_text or features_text in ("", "-", "/", "nan", item.get("name", "")):
                short = rule.required_features[0] if rule.required_features else "项目特征"
                detail = "、".join(rule.required_features[:5]) if rule.required_features else ""
                results.append(CheckResult(
                    category="漏填",
                    severity="error",
                    row=item.get("row"),
                    code=item["code"],
                    message=f"【{rule.name}】项目特征为空",
                    suggestion=f"规范要求填写：{detail}"
                ))
        return results

    def _normalize_unit(self, u: str) -> str:
        u = u.strip().replace('㎡','m²').replace('m2','m²').replace('m3','m³')
        return u

    def _check_wrong_units(self, items: list[dict]) -> list[CheckResult]:
        """检查计量单位是否与规范一致"""
        results = []
        for item in items:
            code_9 = item["code"][:9]
            rule = self.boq_rules.get(code_9)
            if not rule:
                continue

            expected = rule.unit
            actual = self._normalize_unit(item.get("unit", ""))

            if "或" in expected:
                options = [o.strip() for o in expected.split("或")]
                if actual in options:
                    continue

            if actual and actual not in expected and expected not in actual:
                results.append(CheckResult(
                    category="列错",
                    severity="warning",
                    row=item.get("row"),
                    code=item["code"],
                    message=f"单位应为 {expected}，当前为 {actual}",
                    suggestion=f"改为 {expected}"
                ))
        return results

    def _check_dependencies(self, items: list[dict]) -> list[CheckResult]:
        """检查依赖规则：有 A 必须有 B"""
        found_codes = {item["code"][:9] for item in items}
        results = []

        for dep in self.dependency_rules:
            if dep.if_has in found_codes and dep.must_have not in found_codes:
                if_rule = self.boq_rules.get(dep.if_has)
                must_rule = self.boq_rules.get(dep.must_have)
                if_name = if_rule.name if if_rule else dep.if_has
                must_name = must_rule.name if must_rule else dep.must_have

                results.append(CheckResult(
                    category="漏项",
                    severity=dep.severity,
                    row=None,
                    code=dep.if_has,
                    message=f"【{if_name}】需要「{must_name}」({dep.must_have})，但清单中未找到。{dep.reason}",
                    suggestion=f"添加 {dep.must_have}「{must_name}」"
                ))
        return results

    def _check_section_completeness(self, items: list[dict]) -> list[CheckResult]:
        """检查每个分部是否有明显漏项（保守模式——只报高置信度漏项）"""
        found_codes = {item["code"][:9] for item in items}
        results = []

        # 只检查用户确实有涉及的 section
        used_sections = set()
        for code_9 in found_codes:
            for section, codes in self.sections.items():
                if code_9 in codes:
                    used_sections.add(section)

        # 常见的不需要报的项目（特殊工程/地域相关）
        skip_patterns = ["冻土", "淤泥", "管沟", "弧形", "拱形", "薄壳"]

        for section in used_sections:
            all_codes = self.sections[section]
            for code in all_codes:
                if code in found_codes:
                    continue
                rule = self.boq_rules.get(code)
                if not rule:
                    continue
                if any(p in rule.name for p in skip_patterns):
                    continue

                results.append(CheckResult(
                    category="漏项(检查)",
                    severity="warning",
                    row=None,
                    code=code,
                    message=f"分部【{section}】规范含「{rule.name}」，清单中未发现。请确认设计是否需要。",
                    suggestion=f"如设计有此项，添加 {code}「{rule.name}」"
                ))
        return results

    # ==========================================
    # 定额相关检查（数据就绪后启用）
    # ==========================================

    def check_quota_matching(self, items: list[dict]) -> list[CheckResult]:
        """检查定额套用是否合理"""
        results = []
        # 需要定额数据 loaded，暂时留空
        return results

    def stats(self) -> dict:
        """引擎统计"""
        return {
            "boq_rules": len(self.boq_rules),
            "quota_items": len(self.quota_items),
            "dependency_rules": len(self.dependency_rules),
            "sections": len(self.sections),
        }
