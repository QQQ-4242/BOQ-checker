# -*- coding: utf-8 -*-
"""Step 2: Update boq_checker.db with calc_rule and work_content from extracted docx data."""
import sqlite3, json, os, sys

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules', 'boq_checker.db')
EXTRACTED = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules', 'data', 'all_extracted_2013.json')


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    # Load extracted data
    with open(EXTRACTED, 'r', encoding='utf-8') as f:
        extracted = json.load(f)

    # Index by 9-digit code
    extracted_by_code = {}
    for it in extracted:
        code9 = it['code'][:9]
        if code9 not in extracted_by_code:
            extracted_by_code[code9] = it
        else:
            # If duplicate, prefer the one with more data
            existing = extracted_by_code[code9]
            if len(it['calc_rule']) > len(existing.get('calc_rule', '')):
                extracted_by_code[code9] = it

    print(f'Extracted unique codes (9-digit): {len(extracted_by_code)}')

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Get all DB items
    cur.execute('SELECT code, name, features, unit, calc_rule, work_content, section FROM boq_rules')
    db_items = cur.fetchall()
    print(f'DB items: {len(db_items)}')

    updated_calc = 0
    updated_work = 0
    updated_features = 0
    updated_unit = 0
    matched = 0
    unmatched_codes = []

    for db_code, db_name, db_features, db_unit, db_calc, db_work, db_section in db_items:
        code9 = db_code[:9]
        ext = extracted_by_code.get(code9)

        if not ext:
            unmatched_codes.append(code9)
            continue

        matched += 1

        # Build updates
        updates = {}
        ext_calc = ext['calc_rule'].strip()
        ext_work = ext['work_content'].strip()
        ext_features = ext['features'].strip()
        ext_unit = ext['unit'].strip()

        if ext_calc and (not db_calc or len(ext_calc) > len(db_calc)):
            updates['calc_rule'] = ext_calc
            updated_calc += 1

        if ext_work and (not db_work or len(ext_work) > len(db_work)):
            updates['work_content'] = ext_work
            updated_work += 1

        if ext_features and not db_features:
            updates['features'] = ext_features
            updated_features += 1

        if ext_unit and not db_unit:
            updates['unit'] = ext_unit
            updated_unit += 1

        if updates:
            set_clause = ', '.join(f'{k} = ?' for k in updates.keys())
            values = list(updates.values()) + [db_code]
            cur.execute(f'UPDATE boq_rules SET {set_clause} WHERE code = ?', values)

    conn.commit()

    print(f'\nMatched: {matched} / {len(db_items)}')
    print(f'Updated calc_rule: {updated_calc}')
    print(f'Updated work_content: {updated_work}')
    print(f'Updated features: {updated_features}')
    print(f'Updated unit: {updated_unit}')
    print(f'Unmatched codes: {len(unmatched_codes)}')

    # Show a few samples
    cur.execute("SELECT code, name, calc_rule FROM boq_rules WHERE calc_rule != '' LIMIT 5")
    print('\nSample updated items:')
    for r in cur.fetchall():
        print(f'  {r[0]} | {r[1]} | {r[2][:100]}')

    # Final stats
    cur.execute("SELECT COUNT(*) FROM boq_rules WHERE calc_rule != '' AND calc_rule IS NOT NULL")
    final_calc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM boq_rules WHERE work_content != '' AND work_content IS NOT NULL")
    final_work = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM boq_rules")
    total = cur.fetchone()[0]
    print(f'\nFinal: calc_rule {final_calc}/{total}, work_content {final_work}/{total}')

    conn.close()
    print('\nDone.')


if __name__ == '__main__':
    main()
