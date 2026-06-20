# -*- coding: utf-8 -*-
"""Expand two-layer material defense to ALL 8 standards."""
import sqlite3, json, os, sys
from collections import defaultdict, Counter

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules', 'boq_checker.db')

# === COMPREHENSIVE code prefix → material mapping (all standards) ===
# Format: {code_prefix_4: {'confident': [tags], 'check': [tags]}}
# Built by analyzing appendix structure from docx extraction + item names

ALL_MATERIAL_MAP = {
    # ========== GB50854 房建 (01) — already calibrated ==========
    '0101': {'confident': ['土石方']},
    '0102': {'check': ['混凝土']},
    '0103': {'check': ['混凝土', '钢筋']},
    '0104': {'confident': ['砌体']},
    '0105': {'confident': ['混凝土', '钢筋']},
    '0106': {'confident': ['金属结构']},
    '0107': {'confident': ['木结构']},
    '0109': {'confident': ['防水']},
    '0111': {'confident': ['装饰']},
    '0112': {'confident': ['装饰']},
    '0113': {'confident': ['装饰']},
    '0114': {'confident': ['装饰']},
    '0115': {'confident': ['装饰']},
    '011702': {'confident': ['混凝土']},

    # ========== GB50855 仿古 (02) ==========
    # 0201 砖作/砌体 → 砌体
    '0201': {'confident': ['砌体']},
    # 0202 石作 → 装饰
    '0202': {'confident': ['装饰']},
    # 0203 琉璃砌筑 → 砌体 + 装饰
    '0203': {'confident': ['砌体', '装饰']},
    # 0204 混凝土 → 混凝土 + 钢筋
    '0204': {'confident': ['混凝土', '钢筋']},
    # 0205 大木作 → 木结构
    '0205': {'confident': ['木结构']},
    # 0206 小木作/装修 → 木结构 + 装饰
    '0206': {'confident': ['木结构', '装饰']},
    # 0207 屋面 → 防水
    '0207': {'confident': ['防水']},
    # 0208 地面 → 装饰
    '0208': {'confident': ['装饰']},
    # 0209 抹灰/彩画 → 装饰
    '0209': {'confident': ['装饰']},
    # 0210 措施 → check concrete
    '0210': {'check': ['混凝土']},

    # ========== GB50857 市政 (04) ==========
    # 0401 土石方工程
    '0401': {'confident': ['土石方']},
    # 0402 道路工程 → check concrete (路面混凝土)
    '0402': {'check': ['混凝土']},
    # 0403 桥涵工程 → 混凝土 + 钢筋
    '0403': {'confident': ['混凝土', '钢筋']},
    # 0404 隧道工程 → 混凝土 + 砌体
    '0404': {'confident': ['混凝土']},
     # 0405 管网工程 → check concrete + 防水
    '0405': {'check': ['混凝土', '防水']},
    # 0406 水处理工程 → check concrete
    '0406': {'check': ['混凝土']},
    # 0407 垃圾处理 → check concrete
    '0407': {'check': ['混凝土']},
    # 0408 路灯 → 金属结构
    '0408': {'confident': ['金属结构']},
    # 0409 钢筋工程 → 钢筋
    '0409': {'confident': ['钢筋']},
    # 0410 拆除工程 → check concrete
    '0410': {'check': ['混凝土']},
    # 0411 措施项目 → check concrete
    '0411': {'check': ['混凝土']},

    # ========== GB50858 园林 (05) ==========
    # 0501 绿化工程
    # 0502 园路/园桥 → 砌体 + 装饰
    '0502': {'confident': ['砌体', '装饰']},
    # 0503 园林景观 → 混凝土 + 砌体 + 木结构
    '0503': {'check': ['混凝土', '砌体', '木结构']},
    # 0504 措施 → check 混凝土
    '0504': {'check': ['混凝土']},

    # ========== GB50860 构筑物 (07) ==========
    # 0701 池类 → 混凝土 + 钢筋 + 防水
    '0701': {'confident': ['混凝土', '钢筋'], 'check': ['防水']},
    # 0702 烟囱/水塔 → 混凝土 + 钢筋
    '0702': {'confident': ['混凝土', '钢筋']},
    # 0703 措施
    '0703': {'check': ['混凝土']},

    # ========== GB50861 城轨 (08) ==========
    # 0801 土石方 → 土石方
    '0801': {'confident': ['土石方']},
    # 0802 桩基 → 混凝土 + 钢筋
    '0802': {'confident': ['混凝土', '钢筋']},
    # 0803 混凝土结构 → 混凝土 + 钢筋
    '0803': {'confident': ['混凝土', '钢筋']},
    # 0804 装饰 → 装饰
    '0804': {'confident': ['装饰']},
    # 0805 轨道 → 金属结构
    '0805': {'confident': ['金属结构']},
    # 0806 供电 → 金属结构
    '0806': {'confident': ['金属结构']},
    # 0807 智能/监控
    # 0808 措施
    '0808': {'check': ['混凝土']},

    # ========== GB50862 爆破 (09) ==========
    # 0901 露天爆破 → 土石方
    '0901': {'confident': ['土石方']},
    # 0902 地下爆破 → 土石方
    '0902': {'confident': ['土石方']},
    # 0903 硐室爆破 → 土石方
    '0903': {'confident': ['土石方']},
    # 0904 拆除爆破 → 混凝土
    '0904': {'confident': ['混凝土']},
    # 0905 水下爆破 → 土石方
    '0905': {'confident': ['土石方']},
    # 0906 措施
    '0906': {'check': ['混凝土']},
}

# Keywords for "check" verification
CHECK_KEYWORDS = {
    '混凝土': ['混凝土', '砼', '商砼', '灌注桩', '水泥', '深层搅拌',
               '旋喷桩', '地下连续墙', '垫层', '褥垫层', '预制桩',
               '管桩', '方桩', '模板', '支撑'],
    '钢筋': ['钢筋', '钢绞线', '钢筋笼', '预应力', 'HRB', 'CRB', '钢丝'],
    '砌体': ['砖', '砌块', '砌体', '加气', '空心', '实心', '毛石', '料石', '块石'],
    '防水': ['防水', 'SBS', '卷材', '涂膜', '止水带', '防潮', '防渗'],
    '木结构': ['木', '防腐木', '胶合木', '木屋架', '木梁', '木柱', '木楼梯'],
    '金属结构': ['钢', '金属', '型钢', '钢板', '钢管', '钢梁', '钢柱', '钢屋架', '铁'],
    '装饰': ['抹灰', '涂料', '油漆', '块料', '饰面', '裱糊', '吊顶',
             '石材', '面砖', '地砖', '踢脚', '扶手', '栏杆'],
    '土石方': ['土方', '石方', '挖土', '填土', '回填', '爆破', '开挖', '碾压', '平整',
              '沟槽', '基坑', '冻土', '淤泥', '流砂'],
}


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Get tag IDs
    cur.execute('SELECT id, tag_name FROM material_tags')
    tag_ids = {r[1]: r[0] for r in cur.fetchall()}

    # Clear existing appendix-applied tags (keep keyword-based as base)
    # Actually, let's rebuild from scratch — clear ALL, redo keyword, then appendix
    cur.execute('DELETE FROM rule_material_map')
    print('Cleared all tags')

    # Get all rules
    cur.execute('SELECT code, name, features FROM boq_rules')
    all_rules = cur.fetchall()
    print(f'Total rules: {len(all_rules)}')

    # === PHASE 1: Keyword matching (first layer — catch everything) ===
    kw_tags = {
        '混凝土': ['混凝土', '砼', '商砼', '灌注桩'],
        '钢筋': ['钢筋', '钢绞线', '钢筋笼', '预应力筋'],
        '砌体': ['砖基础', '砖墙', '砌块', '砌体', '毛石', '料石'],
        '防水': ['防水', '卷材', '涂膜', '止水带'],
        '土石方': ['土方', '石方', '回填方'],
        '金属结构': ['钢结构', '钢构件', '钢屋架', '钢柱', '钢梁'],
        '木结构': ['木屋架', '木梁', '木柱', '木楼梯', '防腐木', '胶合木'],
        '装饰': ['抹灰', '涂料', '块料', '饰面', '裱糊', '吊顶'],
    }

    kw_stats = Counter()
    for rule_code, rule_name, features_json in all_rules:
        search_text = (rule_name or '')
        if features_json:
            try:
                feats = json.loads(features_json)
                if isinstance(feats, list):
                    search_text += ' ' + ' '.join(feats)
            except: pass

        for tag_name, keywords in kw_tags.items():
            for kw in keywords:
                if kw in search_text:
                    cur.execute(
                        'INSERT OR IGNORE INTO rule_material_map (rule_code, tag_id) VALUES (?, ?)',
                        (rule_code, tag_ids[tag_name])
                    )
                    kw_stats[tag_name] += 1
                    break

    print('\n=== Phase 1: Keyword ===')
    for tag, count in kw_stats.most_common():
        print(f'  {tag}: {count}')

    # === PHASE 2: Appendix structure (second layer — official classification) ===
    confident_stats = Counter()
    check_stats = Counter()
    skip_stats = Counter()

    for rule_code, rule_name, features_json in all_rules:
        # Find matching appendix mapping
        code4 = rule_code[:4]
        code6 = rule_code[:6]

        # Check exact 6-digit match first, then 4-digit
        for prefix, spec in ALL_MATERIAL_MAP.items():
            if len(prefix) == 6 and rule_code.startswith(prefix):
                # Confident tags
                for tag in spec.get('confident', []):
                    if tag in tag_ids:
                        cur.execute(
                            'INSERT OR IGNORE INTO rule_material_map (rule_code, tag_id) VALUES (?, ?)',
                            (rule_code, tag_ids[tag])
                        )
                        confident_stats[tag] += 1
                # Check tags
                for tag in spec.get('check', []):
                    if tag in tag_ids:
                        if any(kw in (rule_name or '') for kw in CHECK_KEYWORDS.get(tag, [])):
                            cur.execute(
                                'INSERT OR IGNORE INTO rule_material_map (rule_code, tag_id) VALUES (?, ?)',
                                (rule_code, tag_ids[tag])
                            )
                            check_stats[tag] += 1
                        else:
                            skip_stats[tag] += 1

        for prefix, spec in ALL_MATERIAL_MAP.items():
            if len(prefix) == 4 and not any(rule_code.startswith(p6) for p6 in ALL_MATERIAL_MAP if len(p6) == 6):
                if rule_code.startswith(prefix):
                    # Confident
                    for tag in spec.get('confident', []):
                        if tag in tag_ids:
                            cur.execute(
                                'INSERT OR IGNORE INTO rule_material_map (rule_code, tag_id) VALUES (?, ?)',
                                (rule_code, tag_ids[tag])
                            )
                            confident_stats[tag] += 1
                    # Check
                    for tag in spec.get('check', []):
                        if tag in tag_ids:
                            if any(kw in (rule_name or '') for kw in CHECK_KEYWORDS.get(tag, [])):
                                cur.execute(
                                    'INSERT OR IGNORE INTO rule_material_map (rule_code, tag_id) VALUES (?, ?)',
                                    (rule_code, tag_ids[tag])
                                )
                                check_stats[tag] += 1
                            else:
                                skip_stats[tag] += 1

    conn.commit()

    print('\n=== Phase 2: Appendix Confident ===')
    for tag, count in confident_stats.most_common():
        print(f'  {tag}: +{count}')
    print('\n=== Phase 2: Appendix Check ===')
    for tag, count in check_stats.most_common():
        print(f'  {tag}: +{count}')

    # === Final stats ===
    print('\n=== Final Material Tag Stats ===')
    for tag_name in tag_ids:
        cur.execute('SELECT COUNT(*) FROM rule_material_map WHERE tag_id = ?', (tag_ids[tag_name],))
        count = cur.fetchone()[0]
        print(f'  {tag_name}: {count}')

    cur.execute('SELECT COUNT(*) FROM boq_rules WHERE code NOT IN (SELECT DISTINCT rule_code FROM rule_material_map)')
    untagged = cur.fetchone()[0]
    print(f'\nUntagged: {untagged}/{len(all_rules)}')

    conn.close()
    print('\nDone.')


if __name__ == '__main__':
    main()
