# -*- coding: utf-8 -*-
"""Step 3: Recalibrate material tags using official GB appendix structure."""
import sqlite3, json, os, sys
from collections import defaultdict, Counter

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules', 'boq_checker.db')

# === GB50854-2013 Code Prefix → Material mapping ===
# Granular: code_4 or code_6 → [materials]
# "confident" = all items under this prefix are this material
# "check" = some items are, keyword filter within prefix
GB50854_MATERIAL_MAP = {
    # Appendix A: 土石方工程
    '0101': {'confident': ['土石方']},
    # Appendix B: 地基处理 — 含混凝土桩/垫层, but not all
    '0102': {'check': ['混凝土']},
    # Appendix C: 桩基工程 — 混凝土桩 + 钢管桩
    '0103': {'check': ['混凝土', '钢筋']},
    # Appendix D: 砌筑工程
    '0104': {'confident': ['砌体']},
    # Appendix E: 混凝土及钢筋混凝土
    '0105': {'confident': ['混凝土', '钢筋']},
    # Appendix F: 金属结构
    '0106': {'confident': ['金属结构']},
    # Appendix G: 木结构
    '0107': {'confident': ['木结构']},
    # Appendix J: 屋面及防水
    '0109': {'confident': ['防水']},
    # Appendix L: 楼地面装饰
    '0111': {'confident': ['装饰']},
    # Appendix M: 墙柱面装饰
    '0112': {'confident': ['装饰']},
    # Appendix N: 天棚
    '0113': {'confident': ['装饰']},
    # Appendix P: 油漆涂料
    '0114': {'confident': ['装饰']},
    # Appendix Q: 其他装饰
    '0115': {'confident': ['装饰']},
    # Appendix R: 措施项目 — ONLY 模板/支撑 are concrete
    '011702': {'confident': ['混凝土']},  # 混凝土模板及支架
    '011703': {'confident': ['混凝土']},  # 垂直运输机械
}

# Keyword check list for "check" prefixes
CHECK_KEYWORDS = {
    '混凝土': ['混凝土', '砼', '商砼', '灌注桩', '水泥', '深层搅拌', '旋喷桩',
               '地下连续墙', '混凝土垫层', '褥垫层'],
    '钢筋': ['钢筋', '钢绞线', '钢筋笼', '预应力', 'HRB', 'CRB'],
}

# Apply: for each item with a "check" prefix, only tag if name matches keyword
def should_tag(material, name):
    if material not in CHECK_KEYWORDS:
        return False
    for kw in CHECK_KEYWORDS[material]:
        if kw in (name or ''):
            return True
    return False

# For other standards, map by standard prefix + appendix
OTHER_STANDARD_MAPPINGS = {
    # 仿古 GB50855 (02)
    '0205': ['混凝土'],
    '0206': ['金属结构'],
    '0207': ['木结构'],
    # 市政 GB50857 (04)
    '0401': ['土石方'],
    '0403': ['混凝土', '钢筋'],
    '0404': ['砌体'],
    '0405': ['防水'],
    # 园林 GB50858 (05)
    '0503': ['混凝土'],
    '0504': ['砌体'],
    # 构筑物 GB50860 (07)
    '0701': ['混凝土', '钢筋'],
    # 城轨 GB50861 (08)
    '0801': ['混凝土'],
    '0802': ['混凝土'],
    '0803': ['混凝土', '钢筋'],
    # 爆破 GB50862 (09)
    '0904': ['混凝土'],
}


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Get all material tags
    cur.execute('SELECT id, tag_name FROM material_tags')
    tag_map = {r[1]: r[0] for r in cur.fetchall()}
    tag_lookup = {v: k for k, v in tag_map.items()}

    # Get all items with current keyword-based tags
    cur.execute('''
        SELECT br.code, br.name, br.section
        FROM boq_rules br
    ''')
    all_items = cur.fetchall()

    # Build appendix material map: code prefix → [(material, 'confident'|'check')]
    appendix_map = {}
    for prefix, spec in GB50854_MATERIAL_MAP.items():
        for tag in spec.get('confident', []):
            appendix_map[(prefix, tag)] = 'confident'
        for tag in spec.get('check', []):
            appendix_map[(prefix, tag)] = 'check'

    # Phase 1: Apply confident tags (appendix structure)
    # Phase 2: Apply check tags (appendix + keyword verification)

    stats = defaultdict(lambda: {'confident': 0, 'check': 0, 'skipped': 0})

    for db_code, db_name, db_section in all_items:
        # Get existing keyword tags
        cur.execute('''
            SELECT GROUP_CONCAT(mt.tag_name)
            FROM rule_material_map rmm
            JOIN material_tags mt ON rmm.tag_id = mt.id
            WHERE rmm.rule_code = ?
        ''', (db_code,))
        row = cur.fetchone()
        existing_str = row[0] if row and row[0] else ''
        existing = [e for e in existing_str.split(',') if e]

        for prefix, spec in GB50854_MATERIAL_MAP.items():
            if not db_code.startswith(prefix):
                continue

            # Confident tags — apply to ALL items under this prefix
            for tag in spec.get('confident', []):
                if tag in tag_map and tag not in existing:
                    cur.execute(
                        'INSERT OR IGNORE INTO rule_material_map (rule_code, tag_id) VALUES (?, ?)',
                        (db_code, tag_map[tag])
                    )
                    stats[tag]['confident'] += 1

            # Check tags — only apply if name matches keyword
            for tag in spec.get('check', []):
                if tag in tag_map and tag not in existing:
                    if should_tag(tag, db_name):
                        cur.execute(
                            'INSERT OR IGNORE INTO rule_material_map (rule_code, tag_id) VALUES (?, ?)',
                            (db_code, tag_map[tag])
                        )
                        stats[tag]['check'] += 1
                    else:
                        stats[tag]['skipped'] += 1

    conn.commit()

    # Show what happened
    print('=== 材料标签校准结果 ===')
    total_added = 0
    for tag_name in tag_map:
        s = stats[tag_name]
        added = s['confident'] + s['check']
        total_added += added
        if added > 0:
            print(f'  {tag_name}: +{added} (confident {s["confident"]}, check {s["check"]}, skipped {s["skipped"]})')
    print(f'\n共补标签: {total_added}')

    # Show 0117 items to verify scaffolding fix
    print('\n=== 验证：0117 措施项目（应该只有模板类有混凝土标签）===')
    cur.execute('''
        SELECT br.code, br.name, GROUP_CONCAT(mt.tag_name)
        FROM boq_rules br
        LEFT JOIN rule_material_map rmm ON br.code = rmm.rule_code
        LEFT JOIN material_tags mt ON rmm.tag_id = mt.id
        WHERE br.code LIKE '0117%'
        GROUP BY br.code
        LIMIT 15
    ''')
    for r in cur.fetchall():
        print(f'  {r[0]} | {r[1][:40]} | tags: {r[2] or "(无)"}')

    # New tag stats
    print('\n=== 最终材料标签统计 ===')
    for tag_name in tag_map:
        cur.execute('''
            SELECT COUNT(*) FROM rule_material_map rmm
            WHERE rmm.tag_id = (SELECT id FROM material_tags WHERE tag_name = ?)
        ''', (tag_name,))
        count = cur.fetchone()[0]
        print(f'  {tag_name}: {count}')

    # Untagged count
    cur.execute('''
        SELECT COUNT(*) FROM boq_rules
        WHERE code NOT IN (SELECT DISTINCT rule_code FROM rule_material_map)
    ''')
    untagged = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM boq_rules')
    total = cur.fetchone()[0]
    print(f'\n未标记: {untagged}/{total}')

    conn.close()
    print('\nDone.')


if __name__ == '__main__':
    main()
