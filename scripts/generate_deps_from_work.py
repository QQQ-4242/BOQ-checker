# -*- coding: utf-8 -*-
"""Step 4: Generate candidate dependency rules from work_content cross-reference."""
import sqlite3, json, os, sys, re
from collections import defaultdict

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules', 'boq_checker.db')

# Keywords in work_content that imply a dependency on another item type
# Format: {keyword_in_work_content: (likely_dependency_code_prefix, reason_template)}
DEPENDENCY_HINTS = [
    # --- Concrete related ---
    ('模板', '011702', '工作内容含模板施工，需套混凝土模板清单'),
    ('浇筑混凝土', '0105', '工作内容含混凝土浇筑，需对应混凝土清单项'),
    ('混凝土搅拌', '0105', '工作内容含混凝土搅拌，需对应混凝土清单项'),
    ('预制混凝土', '0105', '工作内容含预制混凝土构件，需对应预制混凝土清单项'),

    # --- Rebar related ---
    ('钢筋', '010515', '工作内容含钢筋制作安装，需套钢筋工程清单'),
    ('钢筋笼', '010515', '工作内容含钢筋笼，需套钢筋工程清单'),
    ('预应力', '010515', '工作内容含预应力筋，需套预应力钢筋清单'),

    # --- Earthwork related ---
    ('回填', '010103', '工作内容含回填，需套回填方清单'),
    ('挖土', '010101', '工作内容含挖土，需套土方开挖清单'),

    # --- Waterproofing related ---
    ('防水', '010902', '工作内容含防水施工，需套屋面及墙面防水清单'),
    ('防潮', '010903', '工作内容含防潮处理，需套防潮清单'),
    ('止水带', '010902', '工作内容含止水带施工，需套防水清单'),

    # --- Masonry related ---
    ('砌筑', '0104', '工作内容含砌筑，需对应砌体清单'),
    ('砂浆', '0104', '工作内容含砂浆搅拌，需套砌筑清单'),
    ('砖基础', '010401', '工作内容含砖基础，需套砖基础清单'),

    # --- Finishing related ---
    ('抹灰', '0112', '工作内容含抹灰，需套墙柱面抹灰清单'),
    ('涂料', '0114', '工作内容含涂料，需套油漆涂料清单'),
    ('块料', '0111', '工作内容含块料铺贴，需套楼地面清单'),
    ('吊顶', '0113', '工作内容含吊顶，需套天棚清单'),

    # --- Steel structure ---
    ('钢构件', '0106', '工作内容含钢构件制作，需套金属结构清单'),
    ('焊接', '0106', '工作内容含焊接，需套金属结构清单'),
    ('螺栓', '010516', '工作内容含螺栓安装，需套螺栓铁件清单'),

    # --- Pile foundation ---
    ('灌注桩', '010302', '工作内容含灌注桩施工，需套灌注桩清单'),
    ('桩基', '0103', '工作内容含桩基施工，需套桩基清单'),

    # --- Scaffolding / measures ---
    ('脚手架', '011701', '工作内容含脚手架搭拆，需套脚手架清单'),
    ('支撑', '011702', '工作内容含支撑体系，需套模板及支架清单'),
]


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Get ALL rules with work_content
    cur.execute('SELECT code, name, work_content FROM boq_rules WHERE work_content IS NOT NULL AND work_content != ""')
    all_rules = cur.fetchall()
    print(f'Rules with work_content: {len(all_rules)}')

    # Build candidates
    candidates = []  # [(source_code, source_name, dep_code, dep_name, reason)]

    # Also get all rules for name lookup
    code_name_map = {}
    cur.execute('SELECT code, name FROM boq_rules')
    for c, n in cur.fetchall():
        code_name_map[c[:9]] = n

    for src_code, src_name, work_content in all_rules:
        if not work_content:
            continue

        for keyword, dep_prefix, reason_template in DEPENDENCY_HINTS:
            if keyword in (work_content or ''):
                # Find matching dependency items
                cur.execute(
                    "SELECT code, name FROM boq_rules WHERE code LIKE ? || '%' LIMIT 3",
                    (dep_prefix,)
                )
                dep_items = cur.fetchall()
                if dep_items:
                    for dep_code, dep_name in dep_items:
                        # Don't self-reference
                        if dep_code[:9] == src_code[:9]:
                            continue
                        reason = reason_template.replace('需套', f'因"{src_name}"({src_code[:9]})的工作内容含"{keyword}"，建议检查是否配套')
                        candidates.append({
                            'source_code': src_code[:9],
                            'source_name': src_name,
                            'dep_code': dep_code[:9],
                            'dep_name': dep_name,
                            'keyword': keyword,
                            'reason': reason,
                        })

    # Deduplicate
    seen = set()
    unique = []
    for c in candidates:
        key = (c['source_code'], c['dep_code'], c['keyword'])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    print(f'Candidate dependencies: {len(unique)}')

    # Group by keyword/reason type
    by_keyword = defaultdict(list)
    for c in unique:
        by_keyword[c['keyword']].append(c)

    # Show summary by keyword
    print('\n=== 候选依赖规则摘要（按关键词分组）===')
    for keyword, items in sorted(by_keyword.items(), key=lambda x: -len(x[1])):
        print(f'\n【{keyword}】→ {len(items)} 条候选')
        for c in items[:3]:
            print(f'  {c["source_code"]} {c["source_name"][:20]} → {c["dep_code"]} {c["dep_name"][:20]}')
            print(f'    理由: {c["reason"][:120]}')

    # Save candidates to JSON for user review
    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules', 'data')
    out_path = os.path.join(out_dir, 'candidate_dependency_rules.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    print(f'\nSaved to: {out_path}')

    # Also save a Markdown table for easy reading
    md_path = os.path.join(out_dir, 'candidate_dependency_rules.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('# 候选依赖规则\n\n')
        f.write(f'共 {len(unique)} 条，从工作内容交叉分析自动生成。**需要人工逐条验证。**\n\n')
        f.write('| 源清单 | 关键词 | 建议配套 | 依赖清单 |\n')
        f.write('|--------|--------|----------|----------|\n')
        for c in sorted(unique, key=lambda x: x['keyword']):
            f.write(f'| {c["source_code"]} {c["source_name"][:15]} | {c["keyword"]} | {c["dep_code"]} | {c["dep_name"][:15]} |\n')
    print(f'Markdown: {md_path}')

    conn.close()
    print('Done.')


if __name__ == '__main__':
    main()
