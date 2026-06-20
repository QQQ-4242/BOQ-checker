# -*- coding: utf-8 -*-
"""Task 12 + 13: Build work_tags table + generate construction sequence dependency rules."""
import sqlite3, json, os, sys
from collections import defaultdict, Counter

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules', 'boq_checker.db')

# ====== WORK TAG DEFINITIONS ======
WORK_TAGS = [
    ('门窗', '🚪 门窗', '门,窗,卷帘,门窗套,窗台板,窗帘,幕墙,隔断'),
    ('保温隔热', '🔥 保温隔热', '保温,隔热,防腐,抗裂,砂浆,网格布,聚苯板,挤塑板,岩棉'),
    ('屋面', '🏠 屋面', '屋面,瓦屋面,型材屋面,膜结构,屋面防水,檐沟,天沟,雨水管,落水管'),
    ('措施项目', '📐 措施项目', '脚手架,模板,支架,垂直运输,大型机械,排水降水,安全防护,临时设施'),
    ('机电安装', '⚡ 机电安装', '变压器,配电,电缆,开关,插座,灯具,管道,阀门,水泵,风机,空调,消防,报警,弱电,监控'),
    ('绿化景观', '🌳 绿化景观', '乔木,灌木,草坪,花卉,绿篱,假山,园路,园桥,亭,廊,花架'),
    ('其他', '🔧 其他', '拆除,维修,加固,零星,杂项,暂估,暂列,专业分包'),
]

# ====== CONSTRUCTION SEQUENCE DEPENDENCY RULES ======
# Format: (if_has_prefix, must_have_prefix, reason, severity, category)
# "if user has item matching if_has_prefix, should also have item matching must_have_prefix"
CONSTRUCTION_SEQ_DEPS = [
    # --- 基础 → 垫层 (universal) ---
    ('010501', '010501001', '有混凝土基础必有垫层', 'error', '施工工序'),
    ('010502', '010501001', '有混凝土柱必有基础垫层', 'error', '施工工序'),

    # --- 混凝土 → 模板 (universal) ---
    ('0105', '011702', '有混凝土构件必有模板（施工必备）', 'error', '施工工序'),

    # --- 混凝土 → 钢筋 (structural) ---
    ('0105', '010515', '有混凝土构件通常配钢筋（除素混凝土外）', 'warning', '施工工序'),

    # --- 柱 → 梁 → 板 (frame sequence) ---
    ('010502', '010503', '有柱通常有梁（框架结构）', 'warning', '施工工序'),
    ('010503', '010505', '有梁通常有板（楼盖体系）', 'warning', '施工工序'),
    ('010502', '010505', '有柱通常有板', 'warning', '施工工序'),

    # --- 砌体 → 拉结筋 ---
    ('010401', '010515', '砌体墙需拉结筋（抗震构造）', 'warning', '施工工序'),

    # --- 砌体 → 构造柱 ---
    ('010401', '010502', '砌体墙长度超5m需设构造柱', 'info', '施工工序'),

    # --- 屋面 → 防水 ---
    ('010901', '010902', '有屋面必有屋面防水', 'error', '施工工序'),

    # --- 屋面 → 保温 ---
    ('010901', '011001', '有屋面通常有保温（节能要求）', 'warning', '施工工序'),

    # --- 地下结构 → 防水 ---
    ('010501', '010903', '地下混凝土基础需防水', 'error', '施工工序'),

    # --- 门窗 → 过梁 ---
    ('010801', '010503', '门窗口上方需过梁', 'warning', '施工工序'),
    ('010802', '010503', '门窗口上方需过梁', 'warning', '施工工序'),

    # --- 楼地面 → 垫层/找平 ---
    ('011101', '011101001', '有楼地面必有找平层', 'warning', '施工工序'),

    # --- 抹灰 → 涂料 ---
    ('011201', '011401', '有墙面抹灰通常有涂料/油漆', 'info', '施工工序'),

    # --- 挖土 → 回填 ---
    ('010101', '010103', '有挖土方必有回填方', 'error', '施工工序'),

    # --- 桩基 → 截桩 ---
    ('010302', '010301004', '有灌注桩需截桩头', 'error', '施工工序'),

    # --- 金属结构 → 螺栓 ---
    ('010601', '010516', '有钢结构需预埋螺栓', 'error', '施工工序'),

    # --- 钢筋 → 垫块/保护层 ---
    ('010515', '010516', '钢筋工程需预埋铁件（垫块/马凳）', 'info', '施工工序'),

    # --- 安装 → 土建配合 ---
    ('0304', '010516', '配电设备基础需预埋铁件', 'warning', '施工工序'),
    ('0308', '010516', '管道支架需预埋件', 'warning', '施工工序'),

    # --- 市政特有 ---
    ('040101', '040103', '市政挖沟槽需回填', 'error', '施工工序'),
    ('0403', '011702', '市政桥梁混凝土需模板', 'error', '施工工序'),

    # --- 防水 → 找平层 ---
    ('010902', '011101', '屋面防水层下需找平层', 'warning', '施工工序'),
]


def build_work_tags():
    """Create work_tags table and populate."""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Drop old
    cur.execute('DROP TABLE IF EXISTS rule_work_map')
    cur.execute('DROP TABLE IF EXISTS work_tags')

    # Create work tags table
    cur.execute('''
        CREATE TABLE work_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_name TEXT NOT NULL UNIQUE,
            tag_label TEXT NOT NULL,
            keywords TEXT NOT NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE rule_work_map (
            rule_code TEXT NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (rule_code, tag_id),
            FOREIGN KEY (tag_id) REFERENCES work_tags(id)
        )
    ''')

    for tag_name, tag_label, keywords in WORK_TAGS:
        cur.execute(
            'INSERT INTO work_tags (tag_name, tag_label, keywords) VALUES (?, ?, ?)',
            (tag_name, tag_label, keywords)
        )

    # Tag all rules
    cur.execute('SELECT code, name, features FROM boq_rules')
    all_rules = cur.fetchall()

    tag_ids = {}
    cur.execute('SELECT id, tag_name FROM work_tags')
    for tid, tname in cur.fetchall():
        tag_ids[tname] = tid

    stats = Counter()

    for rule_code, rule_name, features_json in all_rules:
        search_text = (rule_name or '')
        if features_json:
            try:
                feats = json.loads(features_json)
                if isinstance(feats, list):
                    search_text += ' ' + ' '.join(feats)
            except: pass

        for tag_name, tag_label, keywords in WORK_TAGS:
            kw_list = [k.strip() for k in keywords.split(',')]
            for kw in kw_list:
                if kw in search_text:
                    cur.execute(
                        'INSERT OR IGNORE INTO rule_work_map (rule_code, tag_id) VALUES (?, ?)',
                        (rule_code, tag_ids[tag_name])
                    )
                    stats[tag_name] += 1
                    break

    # Also tag by code prefix for well-defined categories
    prefix_map = {
        '0108': '门窗',      # 附录H 门窗
        '0110': '保温隔热',  # 附录K 保温隔热防腐
        '0109': '屋面',      # 附录J 屋面及防水(部分)
        '0117': '措施项目',  # 附录R 措施项目
        '03': '机电安装',    # GB50856 安装
        '05': '绿化景观',    # GB50858 园林
    }

    for rule_code, rule_name, features_json in all_rules:
        for prefix, tag_name in prefix_map.items():
            if rule_code.startswith(prefix) and tag_name in tag_ids:
                cur.execute(
                    'INSERT OR IGNORE INTO rule_work_map (rule_code, tag_id) VALUES (?, ?)',
                    (rule_code, tag_ids[tag_name])
                )
                stats[f'{tag_name}(prefix)'] += 1

    conn.commit()

    print('=== 工程类别标签统计 ===')
    for tag_name in tag_ids:
        cur.execute('SELECT COUNT(*) FROM rule_work_map WHERE tag_id = ?', (tag_ids[tag_name],))
        count = cur.fetchone()[0]
        print(f'  {tag_name}: {count}')

    # How many are NOW covered (have either material or work tag)?
    cur.execute('''
        SELECT COUNT(DISTINCT code) FROM boq_rules
        WHERE code IN (SELECT DISTINCT rule_code FROM rule_material_map)
           OR code IN (SELECT DISTINCT rule_code FROM rule_work_map)
    ''')
    covered = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM boq_rules')
    total = cur.fetchone()[0]
    print(f'\nMaterial + Work tagged: {covered}/{total}')
    print(f'Still untagged: {total - covered}')

    conn.close()
    return tag_ids


def build_seq_deps():
    """Insert construction sequence dependency rules into DB."""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Check existing dependency_rules table schema
    cur.execute('PRAGMA table_info(dependency_rules)')
    cols = [r[1] for r in cur.fetchall()]
    print(f'\nDependency table columns: {cols}')

    # Count existing
    cur.execute('SELECT COUNT(*) FROM dependency_rules')
    existing = cur.fetchone()[0]
    print(f'Existing dependency rules: {existing}')

    # Insert construction sequence deps
    added = 0
    skipped = 0
    for if_prefix, must_prefix, reason, severity, category in CONSTRUCTION_SEQ_DEPS:
        # Check if a similar rule already exists
        cur.execute(
            'SELECT id FROM dependency_rules WHERE if_has LIKE ? AND must_have LIKE ?',
            (if_prefix + '%', must_prefix + '%')
        )
        if cur.fetchone():
            skipped += 1
            continue

        cur.execute(
            'INSERT INTO dependency_rules (if_has, must_have, reason, severity, context) VALUES (?, ?, ?, ?, ?)',
            (if_prefix, must_prefix, reason, severity, category)
        )
        added += 1

    conn.commit()

    print(f'Added {added} construction sequence deps, skipped {skipped} duplicates')

    # Show all current deps
    cur.execute('SELECT severity, context, COUNT(*) FROM dependency_rules GROUP BY severity, context')
    print('\nCurrent dependency rules:')
    for r in cur.fetchall():
        print(f'  {r[0]} ({r[1]}): {r[2]}')

    # Save a readable list
    cur.execute('SELECT if_has, must_have, reason, severity, context FROM dependency_rules ORDER BY context, severity')
    all_deps = cur.fetchall()

    md_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules', 'data', 'all_dependency_rules.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('# 全部依赖规则\n\n')
        f.write(f'共 {len(all_deps)} 条\n\n')
        f.write('| 条件 | 必须有的项 | 理由 | 级别 | 来源 |\n')
        f.write('|------|-----------|------|------|------|\n')
        for if_has, must_have, reason, severity, context in all_deps:
            f.write(f'| {if_has} | {must_have} | {reason} | {severity} | {context} |\n')
    print(f'\nSaved: {md_path}')

    conn.close()


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    print('=' * 60)
    print('TASK 12: 工程类别标签')
    print('=' * 60)
    build_work_tags()

    print()
    print('=' * 60)
    print('TASK 13: 施工工序依赖规则')
    print('=' * 60)
    build_seq_deps()

    print('\nDone.')


if __name__ == '__main__':
    main()
