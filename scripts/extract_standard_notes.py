# -*- coding: utf-8 -*-
"""Extract implicit dependency rules from 注 sections in all 8 GB docx."""
import zipfile, os, sys, re, json
from xml.etree import ElementTree as ET

BASE = r'D:/Desktop/QCX/清单 定额/word/13'
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules', 'data', 'standard_notes_deps.json')

# Dependency-relevant patterns
PATTERNS = [
    (r'应[按参].*?相关项目[编码]*列项', 'cross_standard'),
    (r'应[按参].*?([A-G]\.[\d]+).*?列项', 'appendix_ref'),
    (r'不[得应]?.*?包含', 'exclusion'),
    (r'另[行列][项编].*?列项', 'separate_item'),
    (r'包含.*?相[应关].*?项目', 'inclusion_hint'),
    (r'需[要按].*?列项', 'required_item'),
    (r'按.*?GB\s*5\d+\s*相关项目', 'cross_standard_gb'),
    (r'不扣除', 'calc_rule_note'),
]


def extract_notes_from_docx(filepath):
    """Extract all 注 paragraphs with surrounding context."""
    z = zipfile.ZipFile(filepath)
    xml_content = z.read('word/document.xml')
    root = ET.fromstring(xml_content)
    z.close()

    paras = root.findall('.//w:p', NS)
    notes = []

    for i, p in enumerate(paras):
        texts = [t.text for t in p.findall('.//w:t', NS) if t.text]
        line = ''.join(texts).strip()

        # Find 注 paragraphs
        if line.startswith('注') or line.startswith('注：'):
            # Get context: find preceding section heading
            section = 'unknown'
            for j in range(i-1, max(0, i-30), -1):
                prev_text = ''.join(t.text for t in paras[j].findall('.//w:t', NS) if t.text).strip()
                # Look for appendix/section heading patterns
                m = re.match(r'([A-Z]\.\d+|附\s*录\s*[A-Z])', prev_text)
                if m:
                    section = prev_text[:60]
                    break
                m = re.match(r'表\s*[A-Z]', prev_text)
                if m:
                    section = prev_text[:60]
                    break

            # Also get the item table context (preceding table header)
            notes.append({
                'text': line,
                'section': section,
                'para_index': i,
            })

    return notes


def parse_note_to_rule(note, standard_name):
    """Try to parse a 注 into a dependency rule."""
    text = note['text']
    rules = []

    # Pattern: 应按XXX相关项目编码列项
    m = re.search(r'(?:如需|需|应)(.*?)(?:应按|应参照|参见?)(.*?)(?:相关项目[编码]*列项|项目编码列项)', text)
    if m:
        condition = m.group(1).strip('，。、 ')
        target = m.group(2).strip('，。、 ')

        # Determine if_has prefix
        if '桩头' in condition or '截桩' in condition:
            if_has = '010101'  # 土方开挖（挖桩间土）
        elif '回填' in condition and '300' in condition:
            if_has = '050101'  # 绿化用地
        elif '挖填' in condition or '土石方' in condition:
            if_has = '0501'  # 园林
        elif '阀门井' in condition:
            if_has = '050103'  # 绿地喷灌
        elif '钢筋混凝土' in condition or '金属构件' in condition:
            if_has = '0502'  # 园路园桥
        elif '地伏石' in condition or '石望柱' in condition or '石栏杆' in condition:
            if_has = '050201'  # 园路
        elif '台阶' in condition:
            if_has = '050201'  # 园路
        elif '混合类' in condition:
            if_has = '050201'  # 园桥
        else:
            if_has = 'UNKNOWN'

        # Determine must_have
        if '桩基' in target:
            must_have = '0103'
        elif 'GB50854' in target or '房屋建筑' in target:
            if '附录A' in target:
                must_have = '0101'
            elif '混凝土' in target:
                must_have = '0105'
            else:
                must_have = '01'
        elif 'GB50857' in target or '市政' in target:
            must_have = '04'
        elif 'GB50855' in target or '仿古' in target:
            must_have = '02'
        elif 'GB50856' in target or '安装' in target:
            must_have = '03'
        else:
            must_have = 'UNKNOWN'

        if if_has != 'UNKNOWN' and must_have != 'UNKNOWN':
            rules.append({
                'if_has': if_has,
                'must_have': must_have,
                'reason': text[:200],
                'severity': 'warning',
                'source': standard_name,
                'note_section': note['section'],
            })

    # Pattern: 应按...单独编码列项
    m = re.search(r'(.*?)(?:应|需)(?:按|按照)(.*?)(?:单独[编码]*列项|单独列项)', text)
    if m:
        condition = m.group(1).strip('，。、 ')
        target = m.group(2).strip('，。、 ')
        if condition and target:
            rules.append({
                'if_has': 'UNKNOWN',
                'must_have': target[:50],
                'reason': text[:200],
                'severity': 'info',
                'source': standard_name,
                'note_section': note['section'],
            })

    return rules


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    all_notes = []
    all_rules = []

    for fname in sorted(os.listdir(BASE)):
        if not fname.endswith('.docx') or '5085' not in fname:
            continue

        # Extract standard name
        std_match = re.search(r'GB 5085(\d)', fname)
        std_name = f'GB5085{std_match.group(1)}' if std_match else fname[:20]

        path = os.path.join(BASE, fname)
        notes = extract_notes_from_docx(path)
        print(f'\n{std_name}: {len(notes)} 注 paragraphs')

        for note in notes:
            all_notes.append({**note, 'standard': std_name})
            rules = parse_note_to_rule(note, std_name)
            all_rules.extend(rules)
            if rules:
                for r in rules:
                    print(f'  → [{r["severity"]}] {r["reason"][:150]}')

    # Save
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(all_rules, f, ensure_ascii=False, indent=2)

    # Also save all notes for review
    notes_out = OUT.replace('.json', '_all_notes.json')
    with open(notes_out, 'w', encoding='utf-8') as f:
        json.dump(all_notes, f, ensure_ascii=False, indent=2)

    print(f'\n=== Summary ===')
    print(f'Total 注 paragraphs: {len(all_notes)}')
    print(f'Extracted rules: {len(all_rules)}')
    print(f'All notes saved to: {notes_out}')
    print(f'Rules saved to: {OUT}')


if __name__ == '__main__':
    main()
