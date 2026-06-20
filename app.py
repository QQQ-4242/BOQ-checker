# -*- coding: utf-8 -*-
"""
工程量清单检查器 — Web 版
用法：D:/python.exe -m streamlit run app.py
"""
import sys, io, os, json, re, sqlite3, traceback
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
tab_check, tab_ai = st.tabs(["🔍 规范检查", "🤖 AI 识别"])

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

            # === CHECK BUTTONS ===
            st.subheader("🔍 规范检查")

            def run_engine(mode):
                """Callback: store check mode and trigger engine in session_state."""
                st.session_state["_run_mode"] = mode

            b1, b2, b3, b4 = st.columns(4)
            with b1: st.button("📋 特征检查", on_click=run_engine, args=("features",), key="_bc1", use_container_width=True)
            with b2: st.button("📏 单位检查", on_click=run_engine, args=("units",), key="_bc2", use_container_width=True)
            with b3: st.button("🔗 漏项检查", on_click=run_engine, args=("deps",), key="_bc3", use_container_width=True)
            with b4: st.button("🔍 全检", on_click=run_engine, args=("all",), type="primary", key="_bc4", use_container_width=True)

            # === 双维度筛选（分开两个 selectbox，不用 columns 避免 DOM bug）===
            tag_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "rules", "boq_checker.db"))
            tag_conn.row_factory = sqlite3.Row
            tag_cur = tag_conn.cursor()
            tag_cur.execute("SELECT tag_name, tag_label FROM material_tags")
            mat_opts = ["全部材料"] + [row["tag_label"] for row in tag_cur.fetchall()]
            tag_cur.execute("SELECT tag_name, tag_label FROM work_tags")
            work_opts = ["全部类别"] + [row["tag_label"] for row in tag_cur.fetchall()]
            mat_label_to_name = {row["tag_label"]: row["tag_name"] for row in tag_cur.execute("SELECT tag_name, tag_label FROM material_tags")}
            work_label_to_name = {row["tag_label"]: row["tag_name"] for row in tag_cur.execute("SELECT tag_name, tag_label FROM work_tags")}
            tag_conn.close()

            st.caption("筛选（可选，多选=取并集，跨维度=取交集）")
            sel_mat = st.multiselect("🧱 材料", mat_opts[1:], placeholder="不选=全部", key="_sel_mat2")
            sel_work = st.multiselect("📐 工程类别", work_opts[1:], placeholder="不选=全部", key="_sel_work2")

            check_items = user_items
            if sel_mat or sel_work:
                tmp_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "rules", "boq_checker.db"))
                tmp_cur = tmp_conn.cursor()
                allowed = None
                if sel_mat:
                    tags = [mat_label_to_name.get(m, "") for m in sel_mat]
                    ph = ",".join("?" * len(tags))
                    tmp_cur.execute(f"SELECT DISTINCT rule_code FROM rule_material_map rmm JOIN material_tags mt ON rmm.tag_id=mt.id WHERE mt.tag_name IN ({ph})", tags)
                    allowed = {r[0][:9] for r in tmp_cur.fetchall()}
                if sel_work:
                    tags = [work_label_to_name.get(w, "") for w in sel_work]
                    ph = ",".join("?" * len(tags))
                    tmp_cur.execute(f"SELECT DISTINCT rule_code FROM rule_work_map rwm JOIN work_tags wt ON rwm.tag_id=wt.id WHERE wt.tag_name IN ({ph})", tags)
                    wcodes = {r[0][:9] for r in tmp_cur.fetchall()}
                    allowed = wcodes if allowed is None else allowed & wcodes
                tmp_conn.close()
                if allowed:
                    check_items = [it for it in user_items if it["code"][:9] in allowed]
                st.caption(f"筛选命中：{len(check_items)} / {len(user_items)} 项")
            else:
                st.caption(f"未筛选：全部 {len(check_items)} 项")

            check_mode = st.session_state.pop("_run_mode", None)

            if check_mode:
                try:
                    fe = RuleEngine()
                    db_path = os.path.join(os.path.dirname(__file__), "rules", "boq_checker.db")
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()

                    yr = check_year
                    yr_fallback = "2013" if yr == "2024" else "2024"
                    if detected:
                        patterns_all = []
                        for s in detected:
                            patterns_all.append(f"%{s.split()[0]}%{yr}%")
                            patterns_all.append(f"%{s.split()[0]}%{yr_fallback}%")
                        conds = " OR ".join(["section LIKE ?"] * len(patterns_all))
                        cur.execute(f"SELECT * FROM boq_rules WHERE {conds}", patterns_all)
                    else:
                        cur.execute(f"SELECT * FROM boq_rules WHERE section LIKE '%{yr}' OR section LIKE '%{yr_fallback}'")
                    loaded_codes = set()
                    for row in cur.fetchall():
                        if row["code"] in loaded_codes: continue
                        loaded_codes.add(row["code"])
                        feats = json.loads(row["features"]) if row["features"] else []
                        fe.add_boq_rule(BOQItemRule(
                            code=row["code"], name=row["name"],
                            required_features=feats, unit=row["unit"] or "",
                            calc_rule="", work_content=[], section=row["section"] or ""
                        ))

                    if check_mode in ("deps", "all"):
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
                    else:
                        results = fe.check_features(check_items) + fe.check_units(check_items) + fe.check_dependencies(check_items)

                    # Store results + Excel in session_state for external display
                    st.session_state["_out_results"] = [{
                        "severity": r.severity, "row": r.row, "code": r.code,
                        "message": r.message, "suggestion": r.suggestion,
                        "category": getattr(r, "category", "")
                    } for r in results]
                    st.session_state["_out_mode"] = check_mode

                    # Build Excel in engine
                    try:
                        out_df = st.session_state.full_df.copy()
                        if out_df.shape[1] < 8:
                            raise ValueError(f"Excel列数不足 (需要8列GTJ格式，当前{out_df.shape[1]}列)")
                        code_col, features_col, unit_col, name_col = 1, 5, 7, 3
                        filled = 0
                        for r in results:
                            if not r.row: continue
                            ri = r.row - 1
                            if ri >= len(out_df): continue
                            cat = getattr(r, "category", "")
                            sug = r.suggestion or ""
                            if cat == "漏填" and "规范要求填写" in sug:
                                ft = sug.replace("规范要求填写：", "")
                                if str(out_df.iloc[ri, features_col]) in ("nan", "", "-"):
                                    out_df.iloc[ri, features_col] = ft
                                    filled += 1
                            elif cat == "列错" and "改为" in sug:
                                out_df.iloc[ri, unit_col] = sug.split("改为 ")[1]
                                filled += 1
                        buf = io.BytesIO()
                        out_df.to_excel(buf, index=False, header=False)
                        st.session_state["_out_xlsx"] = buf.getvalue()
                        st.session_state["_out_xlsx_label"] = f"⬇️ 下载修正后 Excel（{filled}处已填写）" if filled else "⬇️ 下载 Excel"
                    except Exception as xlsx_err:
                        st.session_state["_out_xlsx"] = None
                        st.session_state["_out_xlsx_err"] = f"Excel生成跳过：{xlsx_err}"

                except Exception as e:
                    st.session_state["_out_error"] = f"检查失败：{e}\n{traceback.format_exc()}"

            # === 完整性扫描（放上面，独立于检查结果）===
            if user_items:
                st.divider()
                st.caption("📋 完整性扫描：检查分部内是否有常见漏项（较慢，按需使用）")
                comp_level = st.selectbox(
                    "常见度阈值",
                    [("仅核心项（推荐）", 3), ("核心+常见项", 2), ("全部含冷门", 1)],
                    format_func=lambda x: x[0], key="_comp_lvl"
                )
                def run_completeness():
                    st.session_state["_run_comp"] = True
                st.button("📋 开始完整性扫描", on_click=run_completeness, key="_btn_comp")

            if st.session_state.pop("_run_comp", False):
                try:
                    fe2 = RuleEngine()
                    conn2 = sqlite3.connect(os.path.join(os.path.dirname(__file__), "rules", "boq_checker.db"))
                    conn2.row_factory = sqlite3.Row
                    cur2 = conn2.cursor()
                    yr2 = check_year
                    yr2b = "2013" if yr2 == "2024" else "2024"
                    if detected:
                        allp = []
                        for s in detected:
                            allp.append(f"%{s.split()[0]}%{yr2}%")
                            allp.append(f"%{s.split()[0]}%{yr2b}%")
                        conds2 = " OR ".join(["section LIKE ?"] * len(allp))
                        cur2.execute(f"SELECT * FROM boq_rules WHERE {conds2}", allp)
                    else:
                        cur2.execute(f"SELECT * FROM boq_rules WHERE section LIKE '%{yr2}' OR section LIKE '%{yr2b}'")
                    loaded2 = set()
                    for row in cur2.fetchall():
                        if row["code"] in loaded2: continue
                        loaded2.add(row["code"])
                        feats2 = json.loads(row["features"]) if row["features"] else []
                        fe2.add_boq_rule(BOQItemRule(
                            code=row["code"], name=row["name"],
                            required_features=feats2, unit=row["unit"] or "",
                            calc_rule="", work_content=[], section=row["section"] or ""
                        ))
                    conn2.close()
                    lvl = st.session_state.get("_comp_lvl", ("", 2))
                    comp_results = fe2.check_section_completeness(check_items, min_level=lvl[1] if isinstance(lvl, tuple) else 2)
                    st.session_state["_comp_out"] = [{
                        "severity": r.severity, "code": r.code,
                        "message": r.message, "suggestion": r.suggestion
                    } for r in comp_results]
                except Exception as e:
                    st.session_state["_comp_err"] = f"完整性扫描失败：{e}"

            comp_out = st.session_state.pop("_comp_out", None)
            comp_err = st.session_state.pop("_comp_err", None)
            if comp_err:
                st.error(comp_err)
            if comp_out is not None:
                c_warns = [r for r in comp_out if r["severity"] == "warning"]
                c_infos = [r for r in comp_out if r["severity"] == "info"]
                st.success(f"完整性扫描完成：{len(c_warns)} 核心项  {len(c_infos)} 常见项")
                for r in comp_out:
                    icon = "🟡" if r["severity"] == "warning" else "🔵"
                    st.caption(f"{icon} {r['code']} — {r['message']}\n→ {r['suggestion']}")

            # === DISPLAY RESULTS (outside try, no DOM issues) ===
            out = st.session_state.pop("_out_results", None)
            out_mode = st.session_state.pop("_out_mode", None)
            out_err = st.session_state.pop("_out_error", None)
            out_xlsx = st.session_state.pop("_out_xlsx", None)
            out_xlsx_label = st.session_state.pop("_out_xlsx_label", "⬇️ 下载 Excel")
            out_xlsx_err = st.session_state.pop("_out_xlsx_err", None)

            if out_err:
                st.error(out_err)

            if out is not None:
                errs = [r for r in out if r["severity"] == "error"]
                warns = [r for r in out if r["severity"] == "warning"]
                st.success(f"完成：{len(errs)} 项需修改  {len(warns)} 项建议核对")

                for r in sorted(out, key=lambda r: r["row"] or 999):
                    icon = "🔴" if r["severity"] == "error" else "🟡"
                    rl = f"第{r['row']}行" if r["row"] else ""
                    st.caption(f"{icon} {rl} {r['code']} — {r['message']}\n→ {r['suggestion']}")

            # Download button always visible
            if user_items:
                st.divider()
                if out_xlsx is not None:
                    st.download_button(out_xlsx_label, data=out_xlsx, file_name=f"boq_{out_mode or 'check'}_已修正.xlsx", key="_dl")
                else:
                    buf = io.BytesIO()
                    st.session_state.full_df.to_excel(buf, index=False, header=False)
                    st.download_button("⬇️ 下载当前 Excel", data=buf.getvalue(), file_name="boq_当前.xlsx", key="_dl_raw")
                if out_xlsx_err:
                    st.caption(out_xlsx_err)

st.caption("💡 数据：GB50854~50862 | 2013+2024规范 | 94条依赖规则 | 8材料+7工程类别标签")
