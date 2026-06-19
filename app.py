# -*- coding: utf-8 -*-
"""
工程量清单检查器 — Web 版
用法：D:/python.exe -m streamlit run app.py
"""
import sys, io, os, json, re, sqlite3
sys.path.insert(0, "D:/Lib/site-packages")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import requests
import streamlit as st

from rules.engine import RuleEngine
from rules.schema import BOQItemRule, DependencyRule
# Verify methods exist
assert hasattr(RuleEngine, 'check_format'), 'check_format missing'
assert hasattr(RuleEngine, 'check_features'), 'check_features missing'
assert hasattr(RuleEngine, 'check_units'), 'check_units missing'

st.set_page_config(page_title="工程量清单检查器", layout="wide")
st.title("📐 工程量清单检查器")

# ---- sidebar: AI API ----
with st.sidebar:
    st.header("⚙️ 设置")
    api_key = st.text_input("DeepSeek API Key (AI识别用)", type="password", placeholder="sk-...")
    model = st.selectbox("模型", ["deepseek-chat", "deepseek-reasoner"], index=0)

# ---- tabs ----
tab_ai, tab_check = st.tabs(["🤖 AI 识别", "🔍 规范检查"])

# ============================================================
# TAB 1: AI OCR
# ============================================================
with tab_ai:
    st.subheader("粘贴 OCR 文字，AI 自动结构化")
    raw_text = st.text_area("微信 OCR 提取后粘贴到这里", height=250, placeholder="从微信 OCR 复制文字后粘贴...")
    if st.button("🚀 AI 识别", type="primary", disabled=not (api_key and raw_text.strip())):
        with st.spinner("AI 正在识别..."):
            try:
                response = requests.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    proxies={"http": None, "https": None},
                    json={"model": model, "messages": [{"role": "user", "content": f"Extract all construction BOQ items from this OCR text.\nOCR Text:\n{raw_text}\nReturn ONLY valid JSON:\n{{\"items\": [{{\"id\": 1, \"code\": \"...\", \"name\": \"...\", \"description\": \"...\", \"unit\": \"...\", \"quantity\": 0.0}}]}}\nquantity must be a number. Missing fields use \"-\"."}]},
                    timeout=90,
                )
                data = response.json()["choices"][0]["message"]["content"]
                if "```json" in data: data = data.split("```json")[1].split("```")[0]
                elif "```" in data: data = data.split("```")[1].split("```")[0]
                items = json.loads(data).get("items", [])
                if items:
                    df = pd.DataFrame(items)
                    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
                    st.success(f"✅ {len(items)} 项")
                    st.dataframe(df, use_container_width=True)
                    c1, c2 = st.columns(2)
                    c1.metric("总项数", len(items))
                    c2.metric("工程量合计", f"{df['quantity'].sum():,.2f}")
                    buf = io.BytesIO()
                    df.to_excel(buf, index=False)
                    st.download_button("⬇️ 下载 Excel", data=buf.getvalue(), file_name="ai_boq_result.xlsx")
            except Exception as e:
                st.error(f"失败：{e}")

# ============================================================
# TAB 2: Check
# ============================================================
with tab_check:
    st.subheader("上传 BOQ Excel，对照规范检查")

    # Filters
    c1, c2, c3 = st.columns(3)
    with c1:
        check_type = st.selectbox("规范类型", ["清单规范", "定额", "全部"])
    with c2:
        check_year = st.selectbox("版本", ["2024", "2013"])
    with c3:
        check_region = st.selectbox("地区", ["四川", "全国通用", "北京", "上海", "广东", "浙江", "江苏", "湖北", "重庆"])

    check_file = st.file_uploader("拖入或点击上传 Excel 文件", type=["xlsx", "xls"])

    if check_file:
        # Cache file bytes for reruns
        is_new = st.session_state.get("_last_file") != check_file.name
        if is_new:
            file_bytes = check_file.getvalue()
            st.session_state._last_file = check_file.name
            st.session_state._file_bytes = file_bytes
            for k in ["fix_step", "fix_list", "working_df", "full_df"]:
                st.session_state.pop(k, None)
        else:
            file_bytes = st.session_state._file_bytes

        df = pd.read_excel(io.BytesIO(file_bytes))
        col_names = list(df.columns)

        # Detect GTJ format
        if all(str(c).startswith("Unnamed") for c in col_names[:5]):
            df_raw = pd.read_excel(io.BytesIO(file_bytes), header=None)
            st.session_state.full_df = df_raw
            header_row = None
            for i in range(min(20, len(df_raw))):
                if "项目编码" in [str(v) for v in df_raw.iloc[i].values]:
                    header_row = i
                    break
            if header_row is not None:
                header_cells = [str(v).strip() for v in df_raw.iloc[header_row].values]
                col_map = {}
                for ci, val in enumerate(header_cells):
                    if "编码" in val: col_map["code"] = ci
                    if "名称" in val: col_map["name"] = ci
                    if "特征" in val: col_map["features"] = ci
                    if "单位" in val or "计量单位" in val: col_map["unit"] = ci
                user_items = []
                for ri in range(header_row + 1, len(df_raw)):
                    row = [str(df_raw.iloc[ri, ci]) if ci < df_raw.shape[1] else "" for ci in range(df_raw.shape[1])]
                    code = row[col_map["code"]].strip() if "code" in col_map else ""
                    name = row[col_map["name"]].strip() if "name" in col_map else ""
                    features = row[col_map["features"]].strip() if "features" in col_map else ""
                    # Skip sub-headers and empty rows
                    if not code and name in ("nan", "", "本页小计", "合计"):
                        continue
                    if not code and not name:
                        continue
                    user_items.append({
                        "code": code if re.match(r"^\d", code) else "",
                        "name": name,
                        "features": features,
                        "unit": row[col_map["unit"]].strip() if "unit" in col_map else "",
                        "quantity": 0, "row": ri + 1,
                    })
                st.write(f"已加载 {len(user_items)} 个清单项 (GTJ格式)")
            else:
                user_items = []
        else:
            st.session_state.full_df = df
            col_map = {}
            for ci, c in enumerate(df.columns):
                if "编码" in str(c): col_map["code"] = ci
                if "名称" in str(c): col_map["name"] = ci
                if "特征" in str(c): col_map["features"] = ci
                if "单位" in str(c): col_map["unit"] = ci
            user_items = []
            for idx, row in df.iterrows():
                code = str(row.iloc[col_map["code"]]).strip() if "code" in col_map else ""
                user_items.append({
                    "code": code if re.match(r"^\d", code) else "",
                    "name": str(row.iloc[col_map["name"]]) if "name" in col_map else "",
                    "features": str(row.iloc[col_map["features"]]) if "features" in col_map else "",
                    "unit": str(row.iloc[col_map["unit"]]) if "unit" in col_map else "",
                    "quantity": 0, "row": idx + 1,
                })
            st.write(f"已加载 {len(user_items)} 个清单项")

        if not user_items:
            st.warning("未识别到有效清单项")
        else:
            # Detect project type
            prefixes = set()
            for item in user_items:
                if len(item["code"]) >= 2 and item["code"][0].isdigit():
                    prefixes.add(item["code"][:2])
            std_map = {"01": "GB50854 房建", "03": "GB50856 安装", "04": "GB50857 市政",
                       "05": "GB50858 园林", "06": "GB50859 矿山", "07": "GB50860 构筑物",
                       "08": "GB50861 城轨", "09": "GB50862 爆破"}
            detected = [std_map[p] for p in prefixes if p in std_map]
            st.info(f"📋 {len(user_items)} 项 | 类型: {', '.join(detected) if detected else '未知'} | {check_year}版 | {check_region}")

            if check_year == "2013":
                st.warning("⚠️ 当前数据库仅有 2024 版规范，2013 版结果可能不准确")

            # === 专业筛选 ===
            section_map = {
                "土方": ("0101",), "砌体": ("0104",), "混凝土": ("0105",),
                "钢筋": ("010515",), "金属": ("0106",), "门窗": ("0108",),
                "防水": ("0109",), "保温": ("0110",), "楼地面": ("0111",),
                "墙柱面": ("0112",), "天棚": ("0113",), "涂料": ("0114",),
                "其他装饰": ("0115",), "措施": ("0117",),
            }
            st.divider()
            st.caption("筛选检查范围（不选=全部）")
            cols = st.columns(7)
            selected_sections = []
            for i, (label, prefixes) in enumerate(section_map.items()):
                with cols[i % 7]:
                    if st.checkbox(label, key=f"sec_{label}"):
                        selected_sections.extend(prefixes)

            # Filter user_items by selected sections
            if selected_sections:
                check_items = [it for it in user_items if any(it["code"].startswith(p) for p in selected_sections)]
            else:
                check_items = user_items

            # === THREE CHECK BUTTONS ===
            st.subheader("🔍 选择检查类型")

            b1, b2, b3 = st.columns(3)
            with b1:
                run_feat = st.button("📋 特征检查", type="primary", help="编码/名称缺失 + 项目特征是否完整")
            with b2:
                run_unit = st.button("📏 单位检查", help="计量单位是否与规范一致")
            with b3:
                run_dep = st.button("🔗 漏项检查", help="跨分部依赖：有A是否必须有B")

            check_mode = None
            if run_feat: check_mode = "features"
            if run_unit: check_mode = "units"
            if run_dep: check_mode = "deps"

            if check_mode:
                with st.spinner("检查中..."):
                    fe = RuleEngine()
                    db_path = os.path.join(os.path.dirname(__file__), "rules", "boq_checker.db")
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()

                    yr = check_year
                    if detected:
                        # Build LIKE patterns: %GB50854%2024%
                        patterns = [f"%{s.split()[0]}%{yr}%" for s in detected]
                        conditions = " OR ".join(["section LIKE ?"] * len(patterns))
                        cur.execute(f"SELECT * FROM boq_rules WHERE {conditions}", patterns)
                    else:
                        cur.execute(f"SELECT * FROM boq_rules WHERE section LIKE '%{yr}'")
                    for row in cur.fetchall():
                        feats = json.loads(row["features"]) if row["features"] else []
                        fe.add_boq_rule(BOQItemRule(
                            code=row["code"], name=row["name"],
                            required_features=feats, unit=row["unit"] or "",
                            calc_rule="", work_content=[], section=row["section"] or ""
                        ))

                    if check_mode == "deps":
                        cur.execute("SELECT * FROM dependency_rules")
                        for row in cur.fetchall():
                            fe.add_dependency(DependencyRule(
                                if_has=row["if_has"], must_have=row["must_have"] or "",
                                reason=row["reason"] or "", severity=row["severity"] or "warning",
                                category=row["context"] or "general"
                            ))

                    conn.close()

                    if check_mode == "features":
                        results = fe.check_features(check_items)
                    elif check_mode == "units":
                        results = fe.check_units(check_items)
                    elif check_mode == "deps":
                        results = fe.check_dependencies(check_items)

                    errs = [r for r in results if r.severity == "error"]
                    warns = [r for r in results if r.severity == "warning"]

                    st.success(f"完成：{len(errs)} 项需修改  {len(warns)} 项建议核对")

                    if not results:
                        st.info("未发现问题")
                    else:
                        # Build row→item lookup
                        item_by_row = {it["row"]: it for it in user_items}
                        for r in sorted(results, key=lambda r: r.row or 999):
                            it = item_by_row.get(r.row, {})
                            icon = "🔴" if r.severity == "error" else "🟡"
                            row_label = f"第{r.row}行" if r.row else ""
                            name_label = it.get("name", "")[:20] if it else ""
                            st.markdown(f"{icon} **{row_label} {r.code}** {name_label}  \n"
                                       f"&nbsp;&nbsp;&nbsp;问题：{r.message}  \n"
                                       f"&nbsp;&nbsp;&nbsp;建议：{r.suggestion}")

                        # Build fixed Excel: fill suggestions directly into cells
                        try:
                            out_df = st.session_state.full_df.copy()
                            # GTJ column layout (0-indexed): 0=序号 1=项目编码 3=项目名称 5=项目特征 7=计量单位
                            features_col = 5
                            unit_col = 7
                            name_col = 3

                            filled = 0
                            new_rows = 0

                            if check_mode in ("features", "units"):
                                for r in results:
                                    if not r.row: continue
                                    ri = r.row - 1
                                    if ri >= len(out_df): continue
                                    if check_mode == "features":
                                        if "规范要求填写" in (r.suggestion or ""):
                                            fill_text = r.suggestion.replace("规范要求填写：", "")
                                            current = str(out_df.iloc[ri, features_col])
                                            if current in ("nan", "", "-"):
                                                out_df.iloc[ri, features_col] = fill_text
                                                filled += 1
                                    elif check_mode == "units":
                                        sug = r.suggestion or ""
                                        if "改为" in sug:
                                            out_df.iloc[ri, unit_col] = sug.split("改为 ")[1]
                                            filled += 1

                            elif check_mode == "deps":
                                seen = set()
                                for r in results:
                                    must_code = r.code
                                    if must_code in seen: continue
                                    seen.add(must_code)
                                    rule = fe.boq_rules.get(must_code)
                                    if rule:
                                        new_row = {i: "" for i in range(out_df.shape[1])}
                                        new_row[code_col] = f"{must_code}（建议补充）"
                                        new_row[name_col] = rule.name
                                        new_row[features_col] = "、".join(rule.required_features[:5]) if rule.required_features else ""
                                        new_row[unit_col] = rule.unit
                                        out_df = pd.concat([out_df, pd.DataFrame([new_row])], ignore_index=True)
                                        new_rows += 1

                            if check_mode == "deps":
                                st.success(f"已新增 {new_rows} 个建议补充项（在 Excel 末尾）")
                            else:
                                st.success(f"已自动填入 {filled} 处")

                            st.divider()
                            buf = io.BytesIO()
                            out_df.to_excel(buf, index=False, header=False)
                            label = f"⬇️ 下载修正后的 Excel"
                            if check_mode == "deps" and new_rows > 0:
                                label = f"⬇️ 下载修正后的 Excel（新增{new_rows}项）"
                            elif filled > 0:
                                label = f"⬇️ 下载修正后的 Excel（{filled}处已填写）"
                            st.download_button(label, data=buf.getvalue(),
                                               file_name=f"boq_{check_mode}_已修正.xlsx")
                        except Exception as e:
                            st.warning(f"Excel生成失败: {e}")

st.caption("💡 数据：GB50854-50862-2024 | 2025四川省定额 | 23条依赖规则")
