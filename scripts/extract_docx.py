# -*- coding: utf-8 -*-
"""Step 1: Extract BOQ items from all 8 GB docx files."""
import zipfile, json, os, re, sys
from xml.etree import ElementTree as ET
from collections import defaultdict

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
BASE = r'D:\Desktop\QCX\清单 定额'

FILES = [
    ('GB 50854-2013', '房屋建筑与装饰'),
    ('GB 50855-2013', '仿古建筑'),
    ('GB 50856-2013', '通用安装'),
    ('GB 50857-2013', '市政'),
    ('GB 50858-2013', '园林绿化'),
    ('GB 50860-2013', '构筑物'),
    ('GB 50861-2013', '城市轨道交通'),
    ('GB 50862-2013', '爆破'),
]

HEADER_KEYS = ['项目编码', '项目名称', '项目特征', '计量单位', '工程量计算规则', '工作内容']


def find_file(base, pattern):
    """Find file by pattern in base dir."""
    for f in os.listdir(base):
        if pattern in f and f.endswith('.docx'):
            return os.path.join(base, f)
    return None


def get_cell_text(cell):
    """Extract clean text from a table cell."""
    texts = []
    for t in cell.findall('.//w:t', NS):
        if t.text:
            texts.append(t.text)
    return ''.join(texts).strip()


def is_item_table(rows):
    """Check if this table is a BOQ item table (has proper header)."""
    if len(rows) < 1:
        return False
    header_cells = [get_cell_text(c) for c in rows[0].findall('.//w:tc', NS)]
    match_count = sum(1 for hk in HEADER_KEYS if any(hk in h for h in header_cells))
    return match_count >= 4


def fix_code_and_name(code, name):
    """Fix split codes: '01010100' + '3挖沟槽土方' → '010101003' + '挖沟槽土方'."""
    if not code or not name:
        return code, name
    # If name starts with digits and code looks incomplete
    name_digits = re.match(r'^(\d+)(.*)', name)
    if name_digits and len(code) >= 6 and len(code) < 12:
        code = code + name_digits.group(1)
        name = name_digits.group(2)
    # Clean code
    code = code.replace(' ', '')
    return code, name


def forward_fill(items):
    """Inherit empty fields from preceding item in same 6-digit group."""
    if not items:
        return items

    # Walk items in order, maintaining last non-empty values per 6-digit group
    last = {}  # prefix → {'calc_rule': ..., 'features': ..., etc.}

    for it in items:
        prefix = it['code'][:6]

        if prefix not in last:
            last[prefix] = {'calc_rule': '', 'work_content': '', 'features': '', 'unit': ''}

        for field in ['calc_rule', 'work_content', 'features', 'unit']:
            if it[field].strip():
                last[prefix][field] = it[field]
            elif last[prefix][field]:
                it[field] = last[prefix][field]

    return items


def extract_table(rows):
    """Extract items from a single item table."""
    items = []
    current_item = None

    for row in rows[1:]:  # skip header
        cells = row.findall('.//w:tc', NS)
        if not cells:
            continue

        vals = [get_cell_text(c) for c in cells]

        # Pad to 6 columns if needed
        while len(vals) < 6:
            vals.append('')

        code = vals[0].replace(' ', '') if len(vals) > 0 else ''
        name = vals[1] if len(vals) > 1 else ''
        features = vals[2] if len(vals) > 2 else ''
        unit = vals[3] if len(vals) > 3 else ''
        calc_rule = vals[4] if len(vals) > 4 else ''
        work_content = vals[5] if len(vals) > 5 else ''

        # Fix split code+name
        code, name = fix_code_and_name(code, name)

        # Skip notes rows
        if code.startswith('注') or name.startswith('注') or (not code and not name and not calc_rule and not work_content):
            continue

        # Skip non-item rows (soil classification, etc.)
        if code and not re.match(r'^\d{6,12}$', code) and not code.startswith('0'):
            continue

        # If this row has a valid code, it's a new item
        if code and re.match(r'^\d{6,12}$', code):
            # Save previous item
            if current_item:
                items.append(current_item)

            current_item = {
                'code': code,
                'name': name,
                'features': features,
                'unit': unit,
                'calc_rule': calc_rule,
                'work_content': work_content,
            }
        elif current_item:
            # Continuation row — append to previous item
            if calc_rule:
                current_item['calc_rule'] += '\n' + calc_rule
            if work_content:
                current_item['work_content'] += '\n' + work_content
            if name and not current_item['name']:
                current_item['name'] = name
            if features and not current_item['features']:
                current_item['features'] = features
            if unit and not current_item['unit']:
                current_item['unit'] = unit

    # Save last item
    if current_item:
        items.append(current_item)

    # Forward-fill empty fields within same 6-digit groups
    items = forward_fill(items)

    return items


def extract_docx(filepath, label):
    """Extract all items from a single docx file."""
    z = zipfile.ZipFile(filepath)
    xml_content = z.read('word/document.xml')
    root = ET.fromstring(xml_content)
    z.close()

    tables = root.findall('.//w:tbl', NS)
    all_items = []
    item_tables = 0

    for tbl in tables:
        rows = tbl.findall('.//w:tr', NS)
        if is_item_table(rows):
            items = extract_table(rows)
            if items:
                all_items.extend(items)
                item_tables += 1

    print(f'  {label}: {item_tables} item tables → {len(all_items)} items')
    return all_items


def normalize_code(code):
    """Normalize to 9-digit comparison code."""
    return code[:9] if len(code) >= 9 else code


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    all_data = {}  # standard_name → items

    for std_code, pattern in FILES:
        filepath = find_file(BASE, pattern)
        if filepath:
            label = f'{std_code} {pattern}'
            items = extract_docx(filepath, label)
            all_data[std_code] = items
        else:
            print(f'  ⚠️ NOT FOUND: {std_code} ({pattern})')

    # Stats
    total = sum(len(v) for v in all_data.values())
    print(f'\nTotal: {total} items across {len(all_data)} standards')

    # Count calc_rule coverage
    with_calc = sum(1 for items in all_data.values() for it in items if it['calc_rule'].strip())
    with_work = sum(1 for items in all_data.values() for it in items if it['work_content'].strip())
    print(f'Items with calc_rule: {with_calc}/{total}')
    print(f'Items with work_content: {with_work}/{total}')

    # Save to JSON
    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules', 'data')
    for std_code, items in all_data.items():
        fname = f'{std_code}_extracted.json'
        fpath = os.path.join(out_dir, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f'  Saved: {fname} ({len(items)} items)')

    # Also save a merged file
    merged = []
    for std_code, items in all_data.items():
        for it in items:
            it['_source'] = std_code
        merged.extend(items)

    merged_path = os.path.join(out_dir, 'all_extracted_2013.json')
    with open(merged_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False)
    print(f'  Saved merged: all_extracted_2013.json ({len(merged)} items)')

    return all_data


if __name__ == '__main__':
    main()
