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
        results.extend(self.check_section_completeness(user_items))
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
        """检查项目特征：空 → 不全 → 完整（梯度判断）"""
        results = []
        for item in items:
            code_9 = item["code"][:9]
            rule = self.boq_rules.get(code_9)
            if not rule or not rule.required_features:
                continue

            features_text = item.get("features", "").strip()
            is_empty = not features_text or features_text in ("", "-", "/", "nan", item.get("name", ""))

            # Parse required features list
            # Format: ["1.土壤类别", "2.挖土深度", "3.弃土运距"] or ["土壤类别", "挖土深度"]
            required = rule.required_features
            parsed_required = []
            for rf in required:
                # Remove numbering like "1.", "1、", "(1)" etc.
                cleaned = rf.strip()
                for pat in [r'^\d+[\.\、\)）]\s*', r'^[（\(]\d+[\)）]\s*']:
                    cleaned = re.sub(pat, '', cleaned)
                if cleaned:
                    parsed_required.append(cleaned)

            if not parsed_required:
                continue

            # Check which required features are present
            if is_empty:
                # All missing
                missing = parsed_required
                detail = "、".join(missing[:5])
                results.append(CheckResult(
                    category="漏填",
                    severity="error",
                    row=item.get("row"),
                    code=item["code"],
                    message=f"【{rule.name}】项目特征为空，规范要求 {len(missing)} 项",
                    suggestion=f"规范要求填写：{detail}"
                ))
            else:
                # Check individual features
                missing = []
                for rf in parsed_required:
                    # Check if key term appears in user's features text
                    # Use the core noun as search key (remove common modifiers)
                    found = False
                    # Try exact match first
                    if rf in features_text:
                        found = True
                    else:
                        # Try partial: extract key nouns
                        key = rf.replace('土壤', '').replace('类别', '').replace('强度', '')[:4]
                        if key and key in features_text:
                            found = True
                        # Try fuzzy: is the entire required feature clearly mentioned
                        for term in rf.split('、'):
                            if term and term in features_text:
                                found = True
                                break

                    if not found:
                        missing.append(rf)

                if missing:
                    detail = "、".join(missing[:5])
                    results.append(CheckResult(
                        category="漏填",
                        severity="warning" if len(missing) <= len(parsed_required) / 2 else "error",
                        row=item.get("row"),
                        code=item["code"],
                        message=f"【{rule.name}】项目特征不全，缺少 {len(missing)}/{len(parsed_required)} 项",
                        suggestion=f"需补充：{detail}"
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
        """检查依赖规则：有 A 必须有 B（if_has/must_have 支持前缀匹配）"""
        found_codes = [item["code"][:9] for item in items]
        results = []

        for dep in self.dependency_rules:
            has_a = any(c.startswith(dep.if_has) for c in found_codes)
            has_b = any(c.startswith(dep.must_have) for c in found_codes)
            if has_a and not has_b:
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

    # ==========================================
    # 常见度评分（用于完整性扫描噪声控制）
    # ==========================================
    # Level 3 = 核心项（几乎所有项目都有）
    # Level 2 = 常见项（大部分项目有）
    # Level 1 = 冷门项（特殊工程才有）
    # Level 0 = 极冷门（跳过不报）

    COMMONNESS_COLD_KW = [
        '冻土', '淤泥', '流砂', '管沟', '弧形', '拱形', '薄壳', '筒壳',
        '爆破', '矿山', '冶炼', '炉窑', '烟囱', '水塔', '冷却塔',
        '贮仓', '贮池', '栈桥', '架空索道', '地铁', '盾构',
        '顶管', '夯管', '沉井', '沉箱', '围堰',
        '琉璃', '斗拱', '雀替', '彩画', '仿古', '古建',
        '人防', '防射线', '隔音', '冷藏', '保温门',
    ]

    COMMONNESS_CORE_PREFIXES = [
        '010101', '010103',  # 土方开挖+回填
        '010201',  # 地基处理（部分）
        '0103',    # 桩基（全部）
        '010401', '010402',  # 砖砌体+砌块砌体
        '0105',    # 混凝土及钢筋混凝土（全部）
        '0106',    # 金属结构（全部）
        '0109',    # 屋面及防水（全部）
        '011101',  # 整体面层
    ]

    COMMONNESS_COMMON_PREFIXES = [
        '010102', '010104',  # 石方+其他土方
        '010202', '010203',  # 基坑支护+其他地基
        '010403', '010404',  # 石砌体+垫层
        '0107',    # 木结构
        '0108',    # 门窗
        '0110',    # 保温隔热防腐
        '011102', '011103',  # 块料面层+橡塑面层
        '0112', '0113', '0114', '0115',  # 墙柱面+天棚+涂料+其他装饰
        '0117',    # 措施项目
    ]

    def _commonness_level(self, code: str, name: str = "", section: str = "") -> int:
        """返回 0-3 的常见度。3=核心 2=常见 1=冷门 0=极冷（跳过）"""
        # Non-房建 items are cold for completeness scan
        if section and 'GB50854' not in section and 'gb50854' not in section.lower():
            return 1

        # Check cold keywords
        for kw in self.COMMONNESS_COLD_KW:
            if kw in (name or ''):
                return 1

        # Check core prefixes
        for prefix in self.COMMONNESS_CORE_PREFIXES:
            if code.startswith(prefix):
                return 3

        # Check common prefixes
        for prefix in self.COMMONNESS_COMMON_PREFIXES:
            if code.startswith(prefix):
                return 2

        # Default: cold
        return 1

    def check_section_completeness(self, items: list[dict], min_level: int = 2) -> list[CheckResult]:
        """完整性扫描：检查每个分部是否有明显漏项。

        Args:
            items: 用户清单项
            min_level: 最低常见度阈值，默认 2（只报核心+常见项，跳过冷门）
        """
        found_codes = [item["code"][:9] for item in items]
        results = []

        # 只检查用户涉及的标准、且用户选中范围内的 section
        used_sections = set()
        for code_9 in found_codes:
            for section, codes in self.sections.items():
                if code_9 in codes:
                    used_sections.add(section)

        for section in used_sections:
            all_codes = self.sections[section]
            for code in all_codes:
                if any(c.startswith(code) for c in found_codes):
                    continue
                rule = self.boq_rules.get(code)
                if not rule:
                    continue

                level = self._commonness_level(code, rule.name, rule.section)
                if level < min_level:
                    continue

                severity = "warning" if level >= 3 else "info"
                label = {3: "核心项", 2: "常见项", 1: "冷门项"}.get(level, "")
                results.append(CheckResult(
                    category="完整性扫描",
                    severity=severity,
                    row=None,
                    code=code,
                    message=f"缺少「{rule.name}」({code}) — {label}",
                    suggestion=f"如设计涉及此项，请在清单中添加 {code}「{rule.name}」"
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
