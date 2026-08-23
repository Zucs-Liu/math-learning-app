import secrets

import streamlit as st

from data_access.admin import fetch_recent_attempts, fetch_teacher_name
from game_data.config import AFFIX_NAMES, BOSS_CONFIGS, CHAPTERS, SLOT_ICONS, SLOT_NAMES, UNITS
from game_logic.combat import simulate_battle
from game_logic.equipment import fixed_text, item_chapter_id, item_text, player_stats
from game_logic.loot import find_inventory_item


def render_admin_panel(db_connection, callbacks):
    announcement_rows = callbacks["announcement_rows"]
    create_announcement = callbacks["create_announcement"]
    create_student = callbacks["create_student"]
    delete_announcement = callbacks["delete_announcement"]
    delete_student = callbacks["delete_student"]
    ensure_teacher_profile = callbacks["ensure_teacher_profile"]
    game_feedback_rows = callbacks["game_feedback_rows"]
    grant_all_pets_to_player = callbacks["grant_all_pets_to_player"]
    mark_feedback_replied = callbacks["mark_feedback_replied"]
    ranking_rows = callbacks["ranking_rows"]
    render_announcement_content = callbacks["render_announcement_content"]
    render_ranking = callbacks["render_ranking"]
    reset_student_pin = callbacks["reset_student_pin"]
    send_mail = callbacks["send_mail"]
    set_announcement_active = callbacks["set_announcement_active"]
    setting_get = callbacks["setting_get"]
    setting_set = callbacks["setting_set"]
    student_learning_detail = callbacks["student_learning_detail"]
    student_question_rows = callbacks["student_question_rows"]
    student_rows = callbacks["student_rows"]
    taipei_time_text = callbacks["taipei_time_text"]
    toggle_admin_progress_chapter = callbacks["toggle_admin_progress_chapter"]
    update_and_activate_announcement = callbacks["update_and_activate_announcement"]
    update_student_real_name = callbacks["update_student_real_name"]
    validate_hero_name = callbacks["validate_hero_name"]
    find_item = find_inventory_item
    st.session_state.pop("teacher_admin_target", None)
    if not st.session_state.admin_authenticated:
        st.session_state.screen = "login"
        st.rerun()
    st.subheader("🧑‍🏫 老師管理後台")
    teacher_default_name = fetch_teacher_name(db_connection) or "老師測試勇者"
    teacher_col1, teacher_col2 = st.columns([2, 1])
    teacher_hero_name = teacher_col1.text_input(
        "老師測試角色名稱", value=teacher_default_name, max_chars=12
    ).strip()
    if teacher_col2.button("進入老師測試角色", type="primary", use_container_width=True):
        teacher_name_error = validate_hero_name(teacher_hero_name)
        if not teacher_name_error:
            st.session_state.active_player = ensure_teacher_profile(teacher_hero_name)
            st.session_state.screen = "home"
            st.rerun()
        else:
            st.warning(teacher_name_error)
    st.caption("老師測試角色不需要學生代碼或額外PIN，也不會占用學生編號或學生排名。")
    if st.button("發送全部六隻寵物給老師測試角色", use_container_width=True):
        ensure_teacher_profile(teacher_hero_name or teacher_default_name)
        granted = grant_all_pets_to_player("__TEACHER__")
        if granted:
            st.success(f"已發送：{'、'.join(granted)}。")
        else:
            st.info("老師測試角色已擁有全部六隻寵物。")
    st.divider()
    admin_section = st.selectbox(
        "選擇管理功能",
        ["建立學生", "帳號管理", "測試進度", "答題紀錄", "戰鬥模擬器", "公告管理", "遊戲反饋"],
        key="admin_section",
    )
    if admin_section == "建立學生":
        registration_enabled = setting_get("registration_enabled") == "1"
        new_registration_state = st.toggle("允許學生自行註冊", value=registration_enabled)
        if new_registration_state != registration_enabled:
            setting_set("registration_enabled", "1" if new_registration_state else "0")
            st.rerun()
        st.divider()
        st.caption("老師也可以代替學生建立帳號；系統會產生一次性顯示的PIN。")
        real_name = st.text_input("學生正式姓名", max_chars=30, key="new_real_name").strip()
        hero_name = st.text_input("勇者名稱", max_chars=12, key="new_hero_name").strip()
        if st.button("產生學生代碼與PIN", type="primary"):
            name_error = validate_hero_name(hero_name)
            if not real_name:
                st.warning("請輸入學生正式姓名。")
            elif name_error:
                st.warning(name_error)
            else:
                generated_pin = f"{secrets.randbelow(1000000):06d}"
                try:
                    st.session_state.created_account = create_student(real_name, hero_name, generated_pin)
                except ValueError as error:
                    st.warning(str(error))
        if st.session_state.created_account:
            account = st.session_state.created_account
            st.success("帳號已建立，PIN只會在這裡顯示，請交給學生保存。")
            st.code(f"正式姓名：{account['real_name']}\n勇者名稱：{account['hero_name']}\n學生代碼：{account['student_code']}\nPIN：{account['pin']}")
    if admin_section == "帳號管理":
        students = student_rows()
        if students:
            st.dataframe(students, hide_index=True, use_container_width=True)
            choices = {f"{row['學生代碼']}｜{row['勇者名稱']}": row["學生代碼"] for row in students}
            selected_label = st.selectbox("選擇學生", choices)
            selected_code = choices[selected_label]
            selected_row = next(row for row in students if row["學生代碼"] == selected_code)
            corrected_name = st.text_input(
                "正式姓名（僅老師可見）", value=selected_row["正式姓名"],
                max_chars=30, key=f"real_name_{selected_code}",
            ).strip()
            save_name_col, confirm_col, delete_col = st.columns([1.25, 1.35, 1])
            if save_name_col.button("儲存正式姓名", disabled=not corrected_name, use_container_width=True):
                update_student_real_name(selected_code, corrected_name)
                st.success("正式姓名已更新。")
                st.rerun()
            confirm_delete = confirm_col.checkbox(
                "確認刪除人物與紀錄", key=f"confirm_delete_{selected_code}"
            )
            if delete_col.button(
                "刪除學生", disabled=not confirm_delete, use_container_width=True,
                key=f"delete_student_{selected_code}",
            ):
                delete_student(selected_code)
                st.success(f"已刪除 {selected_code}。")
                st.rerun()
            if st.button(
                "發送全部六隻寵物（測試）",
                key=f"grant_all_pets_{selected_code}",
                use_container_width=True,
            ):
                granted = grant_all_pets_to_player(selected_code)
                if granted:
                    st.success(f"已發送給 {selected_code}：{'、'.join(granted)}。")
                else:
                    st.info(f"{selected_code} 已擁有全部六隻寵物。")
            detail_profile = student_learning_detail(selected_code)
            if detail_profile:
                detail_stats = player_stats(detail_profile)
                st.write("### 角色等級與能力值")
                stat_cols = st.columns(6)
                stat_cols[0].metric("等級", f"Lv{detail_profile['level']}")
                next_exp = detail_profile["level"] * 100 if detail_profile["level"] < 20 else None
                stat_cols[1].metric(
                    "EXP", f"{detail_profile['exp']} / {next_exp}" if next_exp else "MAX"
                )
                stat_cols[2].metric("HP", f"{detail_stats['hp']:.1f}")
                stat_cols[3].metric("攻擊", f"{detail_stats['attack']:.1f}")
                stat_cols[4].metric("防禦", f"{detail_stats['defense']:.1f}")
                stat_cols[5].metric("攻速", f"{detail_stats['attack_speed']:.2f}/秒")
                special_stats = [
                    ("菁英BOSS初始血量降低", detail_stats["boss_hp_reduction"]),
                    ("第一擊額外扣除菁英BOSS血量", detail_stats["first_hit_percent"]),
                    ("對菁英BOSS傷害", detail_stats["boss_damage_pct"]),
                    ("傷害減免", detail_stats["damage_reduction_pct"]),
                    ("暴擊率", detail_stats["critical_rate"]),
                    ("暴擊傷害", detail_stats["critical_damage"]),
                    ("開場護盾", detail_stats["shield_pct"]),
                    ("菁英BOSS攻速降低", detail_stats["boss_attack_slow_pct"]),
                ]
                active_specials = [f"{name} {value:.0%}" for name, value in special_stats if value]
                st.caption("特殊能力：" + ("｜".join(active_specials) if active_specials else "目前無"))
                st.caption(
                    f"🪙 金幣：{detail_profile.get('coins', 0)}｜"
                    f"💎 融煉石：{detail_profile.get('smelting_stones', 0)}｜"
                    f"部位石：{detail_profile.get('slot_smelting_stones', 0)}｜"
                    f"基礎詞條石：{detail_profile.get('basic_affix_smelting_stones', 0)}｜"
                    f"進階詞條石：{detail_profile.get('advanced_affix_smelting_stones', 0)}"
                )
                st.caption(
                    f"🎫 擊殺券：{detail_profile.get('sweep_tickets', 0)}｜"
                    f"目前稱號：{detail_profile.get('equipped_title') or '未佩戴'}｜"
                    f"已解鎖稱號：{'、'.join(detail_profile.get('titles', [])) or '無'}"
                )
                owned_pets = detail_profile.get("pets", [])
                st.caption(
                    "🐾 已擁有寵物："
                    + (
                        "、".join(
                            f"{pet.get('nickname', pet.get('id', '寵物'))} "
                            f"{'★' * max(1, min(3, int(pet.get('stars', 1))))}"
                            f"{'☆' * (3 - max(1, min(3, int(pet.get('stars', 1)))))}"
                            for pet in owned_pets
                        )
                        if owned_pets else "無"
                    )
                )
    
                st.write("### 學習與通關進度")
                progress_rows = []
                for unit_id, unit in UNITS.items():
                    stars = detail_profile["unit_best_stars"].get(unit_id, 0)
                    progress_rows.append({
                        "單元": unit_id, "名稱": unit["name"],
                        "最高星級": "⭐" * stars if stars else "尚未通關",
                    })
                st.dataframe(progress_rows, hide_index=True, use_container_width=True)
                boss_progress = [
                    f"第一章一般BOSS：{detail_profile.get('boss_wins', 0)}次",
                    f"第一章菁英BOSS：{detail_profile.get('elite_boss_wins', 0)}次",
                    f"第二章一般BOSS：{detail_profile.get('chapter2_boss_wins', 0)}次",
                    f"第二章菁英BOSS：{detail_profile.get('chapter2_elite_boss_wins', 0)}次",
                    f"第三章一般BOSS：{detail_profile.get('chapter3_boss_wins', 0)}次",
                    f"第三章菁英BOSS：{detail_profile.get('chapter3_elite_boss_wins', 0)}次",
                    f"第四章一般BOSS：{detail_profile.get('chapter4_boss_wins', 0)}次",
                    f"第四章菁英BOSS：{detail_profile.get('chapter4_elite_boss_wins', 0)}次",
                    f"第五章一般BOSS：{detail_profile.get('chapter5_boss_wins', 0)}次",
                    f"第五章菁英BOSS：{detail_profile.get('chapter5_elite_boss_wins', 0)}次",
                ]
                st.caption("｜".join(boss_progress))
    
                st.write("### 目前穿戴裝備")
                equipment_rows = []
                for slot, slot_name in SLOT_NAMES.items():
                    uid = detail_profile["equipment"].get(slot)
                    equipped = find_item(detail_profile, uid) if uid else None
                    equipment_rows.append({
                        "部位": f"{SLOT_ICONS[slot]} {slot_name}",
                        "裝備": item_text(equipped) if equipped else "尚未裝備",
                    })
                st.dataframe(equipment_rows, hide_index=True, use_container_width=True)
    
                st.write(f"### 完整物品欄（{len(detail_profile['inventory'])}件）")
                star_counts = {
                    stars: sum(1 for item in detail_profile["inventory"] if item.get("stars") == stars)
                    for stars in range(1, 6)
                }
                st.caption("｜".join(
                    f"{'⭐' * stars}：{count}件" for stars, count in star_counts.items() if count
                ) or "目前沒有物品")
                inventory_rows = []
                sorted_inventory = sorted(
                    detail_profile["inventory"],
                    key=lambda item: (-item.get("stars", 0), list(SLOT_NAMES).index(item["slot"])),
                )
                for item in sorted_inventory:
                    source_id = item_chapter_id(item)
                    unit_key = str(item.get("unit", ""))
                    if item.get("achievement"):
                        if unit_key.endswith("-elite") and source_id in CHAPTERS:
                            source = f"成就／{CHAPTERS[source_id]['number']}菁英BOSS"
                        elif source_id in CHAPTERS:
                            source = f"成就／{CHAPTERS[source_id]['number']}"
                        else:
                            source = "成就"
                    else:
                        source = CHAPTERS[source_id]["number"] if source_id in CHAPTERS else "其他"
                    inventory_rows.append({
                        "穿戴": "✅" if detail_profile["equipment"].get(item["slot"]) == item["uid"] else "",
                        "部位": f"{SLOT_ICONS[item['slot']]} {SLOT_NAMES[item['slot']]}",
                        "裝備名稱": item["name"],
                        "星級": "⭐" * item["stars"],
                        "固定能力": fixed_text(item),
                        "附屬能力": f"{AFFIX_NAMES[item['affix_stat']]} +{item['affix_value']:.0%}",
                        "來源": source,
                    })
                if inventory_rows:
                    st.dataframe(inventory_rows, hide_index=True, use_container_width=True)
                else:
                    st.info("目前物品欄是空的。")
    
                st.write("### 作答明細")
                errors_only = st.toggle("只顯示答錯題目", value=True, key=f"errors_{selected_code}")
                question_rows = student_question_rows(selected_code, errors_only=errors_only)
                if question_rows:
                    st.dataframe(question_rows, hide_index=True, use_container_width=True)
                else:
                    st.info("目前沒有符合條件的題目紀錄；新版上線前的作答無法回溯題目與答案。")
            if st.button("重設為新的6位PIN", use_container_width=True):
                new_pin = reset_student_pin(selected_code)
                st.success(f"{selected_code} 的新PIN：{new_pin}（請立即記下）")
        else:
            st.info("目前尚未建立學生帳號。")
    if admin_section == "測試進度":
        st.write("### BOSS通關進度")
        st.caption("點擊章節名稱展開該章BOSS排名，再點一次即可收合。")
        opened_chapter = st.session_state.get("admin_progress_chapter")
        for chapter_id, chapter in CHAPTERS.items():
            is_open = opened_chapter == chapter_id
            chapter_label = f"{'▼' if is_open else '▶'} {chapter['number']}｜{chapter['name']} BOSS"
            st.button(
                chapter_label,
                key=f"admin_progress_toggle_{chapter_id}",
                use_container_width=True,
                on_click=toggle_admin_progress_chapter,
                args=(chapter_id,),
            )
            if is_open:
                for boss_type, boss_label in (("normal", "一般BOSS"), ("elite", "菁英BOSS")):
                    boss_name = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]["name"]
                    st.write(f"#### {boss_label}｜{boss_name} 最佳排名")
                    boss_rows = ranking_rows(
                        boss_type, chapter_id, include_private_identity=True
                    )
                    if boss_rows:
                        render_ranking(boss_rows)
                    else:
                        st.info(f"目前尚無{boss_label}通關紀錄。")
    
    if admin_section == "答題紀錄":
        attempts = fetch_recent_attempts(db_connection, 200)
        for attempt in attempts:
            attempt["完成時間"] = taipei_time_text(attempt["完成時間"])
        st.write("### 最近200筆答題紀錄")
        if attempts:
            st.dataframe(attempts, hide_index=True, use_container_width=True)
        else:
            st.info("目前尚無答題紀錄。")
    if admin_section == "公告管理":
        st.write("### 📢 公告管理")
        if st.session_state.get("admin_announcement_notice"):
            st.success(st.session_state.pop("admin_announcement_notice"))
        with st.form("create_announcement_form", clear_on_submit=True):
            announcement_title = st.text_input("公告標題", max_chars=80)
            announcement_content = st.text_area(
                "公告內容", height=220, max_chars=3000,
                placeholder="輸入要讓所有學生看到的公告內容……",
            )
            announcement_submitted = st.form_submit_button(
                "發布公告", type="primary", use_container_width=True
            )
        if announcement_submitted:
            if not announcement_title.strip() or not announcement_content.strip():
                st.warning("公告標題與內容都必須填寫。")
            else:
                create_announcement(announcement_title, announcement_content)
                st.success("公告已發布。")
                st.rerun()
        announcements = announcement_rows()
        if announcements:
            st.write("### 已建立的公告")
            for announcement in announcements:
                status = "發布中" if announcement["is_active"] else "已停用"
                with st.expander(
                    f"{announcement['title']}｜{status}｜{announcement['created_at_text']}"
                ):
                    render_announcement_content(announcement["content"])
                    st.divider()
                    st.write("#### 編輯這則公告")
                    with st.form(f"edit_announcement_{announcement['id']}"):
                        edited_title = st.text_input(
                            "公告標題", value=announcement["title"], max_chars=80,
                            key=f"edit_announcement_title_{announcement['id']}",
                        )
                        edited_content = st.text_area(
                            "公告內容", value=announcement["content"], height=220,
                            max_chars=3000,
                            key=f"edit_announcement_content_{announcement['id']}",
                        )
                        save_announcement_edit = st.form_submit_button(
                            "儲存修改並啟用", type="primary", use_container_width=True
                        )
                    if save_announcement_edit:
                        if not edited_title.strip() or not edited_content.strip():
                            st.warning("公告標題與內容都必須填寫。")
                        else:
                            update_and_activate_announcement(
                                announcement["id"], edited_title, edited_content
                            )
                            st.session_state.admin_announcement_notice = (
                                f"公告「{edited_title.strip()}」已更新並重新啟用。"
                            )
                            st.rerun()
                    action_col, confirm_col, delete_col = st.columns([1, 1.2, 1])
                    if action_col.button(
                        "停用" if announcement["is_active"] else "重新發布",
                        key=f"toggle_announcement_{announcement['id']}",
                        use_container_width=True,
                    ):
                        set_announcement_active(
                            announcement["id"], not bool(announcement["is_active"])
                        )
                        st.rerun()
                    confirm_delete = confirm_col.checkbox(
                        "確認永久刪除", key=f"confirm_announcement_{announcement['id']}"
                    )
                    if delete_col.button(
                        "刪除", key=f"delete_announcement_{announcement['id']}",
                        disabled=not confirm_delete, use_container_width=True,
                    ):
                        delete_announcement(announcement["id"])
                        st.rerun()
        else:
            st.info("目前尚未建立公告。")
    if admin_section == "戰鬥模擬器":
        st.write("### ⚔️ 學生戰鬥模擬器")
        st.info("此功能只讀取學生目前的等級與已穿戴裝備；不會修改通關紀錄、排名、經驗值、獎勵或學生資料。")
        simulator_students = student_rows()
        if not simulator_students:
            st.warning("目前沒有可供模擬的學生帳號。")
        else:
            student_options = {
                f"{row['學生代碼']}｜{row['正式姓名']}｜{row['勇者名稱']}": row["學生代碼"]
                for row in simulator_students
            }
            simulator_student_label = st.selectbox(
                "選擇學生",
                list(student_options),
                key="battle_simulator_student",
            )
            simulator_chapter = st.selectbox(
                "選擇章節",
                list(CHAPTERS),
                format_func=lambda chapter_id: (
                    f"{CHAPTERS[chapter_id]['number']}｜{CHAPTERS[chapter_id]['name']}"
                ),
                key="battle_simulator_chapter",
            )
            simulator_boss_type = st.radio(
                "選擇 BOSS",
                ["normal", "elite"],
                format_func=lambda boss_type: (
                    f"{'普通' if boss_type == 'normal' else '菁英'} BOSS｜"
                    f"{BOSS_CONFIGS[f'{simulator_chapter}_{boss_type}']['name']}"
                ),
                horizontal=True,
                key="battle_simulator_boss_type",
            )
            if st.button("開始唯讀模擬", type="primary", use_container_width=True):
                simulator_code = student_options[simulator_student_label]
                simulator_profile = student_learning_detail(simulator_code)
                if simulator_profile is None:
                    st.error("找不到這位學生的資料，請重新整理後再試一次。")
                else:
                    simulator_stats = player_stats(simulator_profile)
                    simulator_config = BOSS_CONFIGS[
                        f"{simulator_chapter}_{simulator_boss_type}"
                    ]
                    try:
                        simulator_result = simulate_battle(
                            simulator_stats,
                            simulator_boss_type,
                            simulator_chapter,
                        )
                    except RuntimeError as error:
                        st.error(f"模擬失敗：{error}")
                    else:
                        st.write("#### 學生目前能力")
                        stat_columns = st.columns(5)
                        stat_columns[0].metric("等級", f"Lv{simulator_profile['level']}")
                        stat_columns[1].metric("HP", f"{simulator_stats['hp']:.1f}")
                        stat_columns[2].metric("攻擊", f"{simulator_stats['attack']:.1f}")
                        stat_columns[3].metric("防禦", f"{simulator_stats['defense']:.1f}")
                        stat_columns[4].metric("攻速", f"{simulator_stats['attack_speed']:.2f}/秒")
                        special_parts = []
                        special_labels = {
                            "boss_hp_reduction": "菁英BOSS初始血量降低",
                            "first_hit_percent": "第一擊額外扣除菁英BOSS血量",
                            "boss_damage_pct": "對菁英BOSS傷害",
                            "damage_reduction_pct": "受到傷害降低",
                            "critical_rate": "暴擊率",
                            "critical_damage": "暴擊傷害加成",
                            "shield_pct": "開場護盾",
                            "boss_attack_slow_pct": "菁英BOSS攻擊減速",
                        }
                        for stat_key, label in special_labels.items():
                            if simulator_stats[stat_key] > 0:
                                special_parts.append(
                                    f"{label} {simulator_stats[stat_key] * 100:.0f}%"
                                )
                        st.caption(
                            "特殊能力：" + ("｜".join(special_parts) if special_parts else "無")
                        )
    
                        simulator_events = simulator_result["events"]
                        first_event = simulator_events[0]
                        last_event = simulator_events[-1]
                        hero_hits = sum(
                            event["text"].startswith("勇者第") for event in simulator_events
                        )
                        boss_hits = sum(
                            event["text"].startswith("BOSS第") for event in simulator_events
                        )
                        skill_hits = sum(
                            event["text"].startswith("BOSS施放技能")
                            for event in simulator_events
                        )
                        st.write("#### 模擬結果")
                        if simulator_result["victory"]:
                            st.success(f"模擬獲勝，戰鬥時間 {simulator_result['duration']:.2f} 秒。")
                        else:
                            st.error(f"模擬戰敗，戰鬥時間 {simulator_result['duration']:.2f} 秒。")
                        result_columns = st.columns(4)
                        result_columns[0].metric(
                            "勇者剩餘 HP",
                            f"{last_event['player_hp']:.1f} / {first_event['player_hp']:.1f}",
                        )
                        result_columns[1].metric(
                            "BOSS 剩餘 HP",
                            f"{last_event['boss_hp']:.1f} / {first_event['boss_hp']:.1f}",
                        )
                        result_columns[2].metric("勇者攻擊次數", hero_hits)
                        result_columns[3].metric("BOSS攻擊／技能", f"{boss_hits}／{skill_hits}")
                        st.caption(
                            f"{simulator_config['name']}：原始 HP {simulator_config['hp']}、"
                            f"攻擊 {simulator_config['damage']}、每 {simulator_config['interval']:g} 秒攻擊一次。"
                        )
                        st.write("#### 完整戰鬥明細")
                        st.dataframe(
                            [
                                {
                                    "時間": f"{event['time']:.2f} 秒",
                                    "事件": event["text"],
                                    "勇者 HP": round(event["player_hp"], 1),
                                    "BOSS HP": round(event["boss_hp"], 1),
                                }
                                for event in simulator_events
                            ],
                            hide_index=True,
                            use_container_width=True,
                        )
    
    if admin_section == "遊戲反饋":
        st.write("### 學生遊戲反饋")
        if st.session_state.get("admin_reply_notice"):
            st.success(st.session_state.pop("admin_reply_notice"))
        feedback_rows = game_feedback_rows()
        if feedback_rows:
            feedback_counts = {}
            for feedback_row in feedback_rows:
                category = feedback_row["問題分類"]
                feedback_counts[category] = feedback_counts.get(category, 0) + 1
            st.write("#### 問題分類統計")
            st.dataframe(
                [
                    {"問題分類": category, "回饋數量": count}
                    for category, count in sorted(
                        feedback_counts.items(), key=lambda item: (-item[1], item[0])
                    )
                ],
                hide_index=True,
                use_container_width=True,
            )
            category_options = ["全部"] + sorted({row["問題分類"] for row in feedback_rows})
            selected_feedback_category = st.selectbox(
                "問題分類篩選", category_options, key="admin_feedback_category"
            )
            visible_feedback = feedback_rows
            if selected_feedback_category != "全部":
                visible_feedback = [
                    row for row in feedback_rows
                    if row["問題分類"] == selected_feedback_category
                ]
            st.caption(f"目前顯示 {len(visible_feedback)} 則回饋，最新回饋排在最上方。")
            st.dataframe(visible_feedback, hide_index=True, use_container_width=True)
            feedback_choices = {
                f"#{row['編號']}｜{row['正式姓名']}｜{row['問題分類']}｜{row['回覆狀態']}": row
                for row in visible_feedback
            }
            selected_feedback_label = st.selectbox(
                "選擇要回覆的反饋", list(feedback_choices), key="admin_feedback_reply_target"
            )
            selected_feedback = feedback_choices[selected_feedback_label]
            st.caption("學生問題：" + selected_feedback["回饋內容"])
            with st.form("admin_feedback_reply_form", clear_on_submit=True):
                reply_message = st.text_area(
                    "老師回覆", placeholder="輸入要寄到勇者信箱的內容……", max_chars=2000
                )
                st.caption("如需補發獎勵，可填寫附件；沒有則保持為0。")
                reward_cols = st.columns(3)
                reward_coins = reward_cols[0].number_input("金幣", min_value=0, step=100)
                reward_tickets = reward_cols[1].number_input("擊殺券", min_value=0, step=1)
                reward_stones = reward_cols[2].number_input("融煉石", min_value=0, step=1)
                reply_submitted = st.form_submit_button(
                    "寄出回覆", type="primary", use_container_width=True
                )
            if reply_submitted:
                if not reply_message.strip():
                    st.warning("請先輸入回覆內容。")
                else:
                    reward = {
                        "coins": int(reward_coins),
                        "sweep_tickets": int(reward_tickets),
                        "smelting_stones": int(reward_stones),
                    }
                    reward = {key: value for key, value in reward.items() if value > 0}
                    send_mail(
                        selected_feedback["學生代碼"],
                        f"老師回覆｜{selected_feedback['問題分類']}",
                        reply_message,
                        reward or None,
                    )
                    mark_feedback_replied(selected_feedback["編號"])
                    st.session_state.admin_reply_notice = "回覆已寄到學生的勇者信箱，該筆反饋已標示為已回覆。"
                    st.rerun()
        else:
            st.info("目前還沒有學生送出遊戲反饋。")
    if st.button("登出管理後台"):
        st.session_state.admin_authenticated = False
        st.session_state.created_account = None
        st.session_state.screen = "login"
        st.rerun()
