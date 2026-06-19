"""
数据导入器 — 从 Word/Excel/JSON 导入规范与定额数据
"""
import json
import re
from pathlib import Path
from rules.schema import BOQItemRule, QuotaItem, DependencyRule


class WordImporter:
    """从 Word 文件导入定额数据"""

    @staticmethod
    def from_docx(filepath: str) -> list[dict]:
        """读取 Word 文件，返回原始表格数据"""
        import sys
        sys.path.insert(0, "D:/Lib/site-packages")
        from docx import Document

        doc = Document(filepath)
        tables_data = []

        for table in doc.tables:
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                rows.append(cells)
            if rows:
                tables_data.append(rows)

        return tables_data


class JSONImporter:
    """从 JSON 文件导入结构化规则"""

    @staticmethod
    def load_boq_rules(filepath: str) -> list[BOQItemRule]:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        rules = []
        for item in data.get("items", []):
            rules.append(BOQItemRule(
                code=item["code"],
                name=item["name"],
                required_features=item.get("required_features", []),
                unit=item.get("unit", ""),
                calc_rule=item.get("calc_rule", ""),
                work_content=item.get("work_content", []),
                section=item.get("section", ""),
                cross_refs=item.get("cross_refs", []),
                notes=item.get("notes", []),
            ))
        return rules

    @staticmethod
    def load_quota_items(filepath: str) -> list[QuotaItem]:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        items = []
        for item in data.get("items", []):
            items.append(QuotaItem(
                code=item["code"],
                name=item["name"],
                unit=item.get("unit", ""),
                labor=item.get("labor", {}),
                materials=item.get("materials", {}),
                machinery=item.get("machinery", {}),
                applicable_boq_codes=item.get("applicable_boq_codes", []),
                section=item.get("section", ""),
            ))
        return items

    @staticmethod
    def load_dependency_rules(filepath: str) -> list[DependencyRule]:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        rules = []
        for item in data.get("rules", []):
            rules.append(DependencyRule(
                if_has=item["if_has"],
                must_have=item["must_have"],
                reason=item["reason"],
                severity=item.get("severity", "warning"),
                category=item.get("category", "cross_section"),
            ))
        return rules


class ManualRules:
    """手工编写的核心依赖规则（等 Word 数据入库后逐步替换）"""

    @staticmethod
    def core_dependencies() -> list[DependencyRule]:
        """40 条高置信度依赖规则"""
        rules = []

        # === 土方工程 ===
        rules.append(DependencyRule("010103001", "010101003", "回填方必须有开挖来源（沟槽/基坑/一般土方）", "error", "same_section"))
        rules.append(DependencyRule("010103001", "010101004", "回填方必须有开挖来源", "warning", "same_section"))
        rules.append(DependencyRule("010103002", "010101002", "余方弃置必须有挖方", "error", "same_section"))

        # === 混凝土工程 ===
        rules.append(DependencyRule("010501001", "010515001", "混凝土垫层需要钢筋（如设计有配筋）", "info", "cross_section"))
        rules.append(DependencyRule("010515001", "010501001", "有钢筋必有混凝土构件", "error", "cross_section"))
        rules.append(DependencyRule("010502001", "010515001", "矩形柱需要钢筋", "error", "cross_section"))
        rules.append(DependencyRule("010503002", "010515001", "矩形梁需要钢筋", "error", "cross_section"))
        rules.append(DependencyRule("010505001", "010515001", "有梁板需要钢筋", "error", "cross_section"))
        rules.append(DependencyRule("010508001", "010515001", "后浇带需要钢筋（不单独列项，并入对应构件）", "info", "cross_section"))

        # === 砌体工程 ===
        rules.append(DependencyRule("010401004", "010515001", "多孔砖墙需要砌体加固钢筋", "warning", "cross_section"))
        rules.append(DependencyRule("010401004", "010501001", "砌体墙通常需要混凝土垫层", "info", "cross_section"))

        # === 防水工程 ===
        rules.append(DependencyRule("010902001", "011101006", "屋面卷材防水需要找平层", "warning", "cross_section"))
        rules.append(DependencyRule("010902003", "011101006", "屋面刚性层需要找平层", "warning", "cross_section"))
        rules.append(DependencyRule("010904001", "011101006", "楼地面防水需要找平层", "warning", "cross_section"))
        rules.append(DependencyRule("010904002", "011101006", "楼地面涂膜防水需要找平层", "warning", "cross_section"))

        # === 装饰装修 ===
        rules.append(DependencyRule("011102001", "011105002", "石材楼地面通常需要石材踢脚线", "info", "cross_section"))
        rules.append(DependencyRule("011106001", "011503001", "楼梯面层通常需要栏杆/扶手", "info", "cross_section"))
        rules.append(DependencyRule("011102003", "011105003", "块料楼地面通常需要块料踢脚线", "info", "cross_section"))

        # === 门窗 ===
        rules.append(DependencyRule("010802001", "010807001", "有金属门通常有金属窗", "info", "cross_section"))

        # === 保温 ===
        rules.append(DependencyRule("011001001", "010902001", "保温屋面通常需要防水层", "warning", "cross_section"))

        return rules
