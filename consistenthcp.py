
import streamlit as st
import pandas as pd
from datetime import timedelta
import io

# ==========================================
# 页面配置
# ==========================================
st.set_page_config(page_title="伊赫莱客户识别系统", layout="wide")
st.title("伊赫莱连续送检和连续新星客户识别")

# ==========================================
# 侧边栏：文件上传
# ==========================================
st.sidebar.header("数据上传区")
st.sidebar.markdown("请上传原始数据报告：")

file_sending = st.sidebar.file_uploader("伊赫莱送检情况-每天更新", type=['csv', 'xlsx'])
file_np = st.sidebar.file_uploader("伊赫莱NP-每天更新", type=['csv', 'xlsx'])

# ==========================================
# 顶部交互：参数设置
# ==========================================
st.markdown("### 1. 设定计算周期")
x_months = st.number_input("要求计算过去 X 个月的情况", min_value=1, value=3, step=1)

# ==========================================
# 辅助函数
# ==========================================
def load_data(file):
    if file.name.endswith('.csv'):
        return pd.read_csv(file)
    else:
        return pd.read_excel(file)

def get_period_label(date, anchor_date):
    """计算日期属于第几个月（从1开始，1代表最近的一个月）"""
    days_diff = (anchor_date - date).days
    return (days_diff // 30) + 1

def check_column(df, possible_names, file_label):
    """自动识别列名"""
    for name in possible_names:
        if name in df.columns:
            return name
    st.error(f"在文件【{file_label}】中未找到关键列: {possible_names}")
    return None

# ==========================================
# 主程序逻辑
# ==========================================

if file_sending is not None and file_np is not None:
    try:
        # 1. 读取数据
        df_sending = load_data(file_sending)
        df_np = load_data(file_np)

        # 2. 列名识别 (兼容用户描述与实际文件可能存在的差异)
        col_date_s = check_column(df_sending, ['送检日期', '日期'], "送检表-日期")
        col_adv_s = check_column(df_sending, ['倡导者名字', '倡导者'], "送检表-倡导者")

        col_date_n = check_column(df_np, ['日期', '送检日期'], "NP表-日期")
        col_adv_n = check_column(df_np, ['倡导者', '倡导者名字'], "NP表-倡导者")

        if all([col_date_s, col_adv_s, col_date_n, col_adv_n]):

            # 3. 日期格式化
            df_sending['Date_Obj'] = pd.to_datetime(df_sending[col_date_s], errors='coerce')
            df_np['Date_Obj'] = pd.to_datetime(df_np[col_date_n], errors='coerce')

            df_sending = df_sending.dropna(subset=['Date_Obj'])
            df_np = df_np.dropna(subset=['Date_Obj'])

            # 4. 确定时间锚点 (Anchor Date) - 规则：使用表格最后一行的日期
            # 这里取两张表中最后一行的日期的最大值，或者您可以指定只看某张表
            last_date_s = df_sending.iloc[-1]['Date_Obj']
            last_date_n = df_np.iloc[-1]['Date_Obj']

            # 逻辑：取两者中较晚的那个日期作为整体分析的基准“今天”
            anchor_date = max(last_date_s, last_date_n)

            # 计算起始日期
            total_days = x_months * 30
            start_date = anchor_date - timedelta(days=total_days - 1)

            st.info(f"📅 **分析周期说明**：\n\n"
                    f"**基准日期 (取自表格末行)**：{anchor_date.strftime('%Y-%m-%d')}\n\n"
                    f"**起始日期 (往前推{total_days}天)**：{start_date.strftime('%Y-%m-%d')}")
            st.markdown("---")

            # 5. 数据过滤与索引
            mask_s = (df_sending['Date_Obj'] >= start_date) & (df_sending['Date_Obj'] <= anchor_date)
            mask_n = (df_np['Date_Obj'] >= start_date) & (df_np['Date_Obj'] <= anchor_date)

            df_s_filtered = df_sending.loc[mask_s].copy()
            df_n_filtered = df_np.loc[mask_n].copy()

            # 添加月份索引 (1=最近月)
            df_s_filtered['Month_Idx'] = df_s_filtered['Date_Obj'].apply(lambda x: get_period_label(x, anchor_date))
            df_n_filtered['Month_Idx'] = df_n_filtered['Date_Obj'].apply(lambda x: get_period_label(x, anchor_date))

            # ==========================================
            # 核心算法
            # ==========================================

            # --- A. 连续送检识别 ---
            # 聚合计算
            monthly_s = df_s_filtered.groupby([col_adv_s, 'Month_Idx']).size().reset_index(name='Count')
            # 获取元数据 (取最近的一条记录)
            adv_meta_s = df_s_filtered.sort_values('Date_Obj', ascending=False).groupby(col_adv_s).first().reset_index()

            res_sending = []
            for _, row in adv_meta_s.iterrows():
                name = row[col_adv_s]
                hospital = row['医院名称'] if '医院名称' in row else 'Unknown'

                # 阈值判定
                threshold = 4 if '复旦大学附属肿瘤医院' in str(hospital) else 2

                is_continuous = True
                for m in range(1, x_months + 1):
                    c = monthly_s[(monthly_s[col_adv_s] == name) & (monthly_s['Month_Idx'] == m)]['Count'].sum()
                    if c < threshold:
                        is_continuous = False
                        break

                if is_continuous:
                    res_sending.append({
                        '姓名': name,
                        '所在医院': hospital,
                        'RCL': row.get('RCL', ''),
                        'LEL': row.get('LEL', '')
                    })

            df_res_s = pd.DataFrame(res_sending)

            # --- B. 连续处方识别 ---
            monthly_n = df_n_filtered.groupby([col_adv_n, 'Month_Idx']).size().reset_index(name='Count')
            adv_meta_n = df_n_filtered.sort_values('Date_Obj', ascending=False).groupby(col_adv_n).first().reset_index()

            res_np = []
            for _, row in adv_meta_n.iterrows():
                name = row[col_adv_n]
                hospital = row['医院名称'] if '医院名称' in row else 'Unknown'

                # 阈值判定：每月>=2
                threshold = 2

                is_continuous = True
                for m in range(1, x_months + 1):
                    c = monthly_n[(monthly_n[col_adv_n] == name) & (monthly_n['Month_Idx'] == m)]['Count'].sum()
                    if c < threshold:
                        is_continuous = False
                        break

                if is_continuous:
                    res_np.append({
                        '姓名': name,
                        '所在医院': hospital,
                        'RCL': row.get('RCL', ''),
                        'LEL': row.get('LEL', '')
                    })

            df_res_n = pd.DataFrame(res_np)

            # ==========================================
            # 结果展示区 (按 LEL 分组)
            # ==========================================
            st.markdown("### 2. 识别结果展示")

            all_lels = set()
            if not df_res_s.empty: all_lels.update(df_res_s['LEL'].dropna().unique())
            if not df_res_n.empty: all_lels.update(df_res_n['LEL'].dropna().unique())

            if not all_lels:
                st.warning("未发现符合条件的客户。")

            for lel in sorted(list(all_lels)):
                with st.container():
                    st.markdown(f"#### 👤 LEL: {lel}")
                    c1, c2 = st.columns(2)

                    with c1:
                        st.markdown("**🧪 连续送检客户**")
                        if not df_res_s.empty:
                            sub = df_res_s[df_res_s['LEL'] == lel]
                            if not sub.empty:
                                for _, u in sub.iterrows():
                                    st.success(f"{u['姓名']} ({u['所在医院']})")
                            else:
                                st.caption("无")
                        else:
                            st.caption("无")

                    with c2:
                        st.markdown("**💊 连续处方客户**")
                        if not df_res_n.empty:
                            sub = df_res_n[df_res_n['LEL'] == lel]
                            if not sub.empty:
                                for _, u in sub.iterrows():
                                    st.info(f"{u['姓名']} ({u['所在医院']})")
                            else:
                                st.caption("无")
                        else:
                            st.caption("无")
                    st.markdown("---")

            # ==========================================
            # 导出区
            # ==========================================
            st.markdown("### 3. 结果导出")

            # 导出送检表 (按月)
            if not df_res_s.empty:
                export_s = df_res_s.copy()
                for i, row in export_s.iterrows():
                    name = row['姓名']
                    # 填充每月数据
                    for m in range(1, x_months + 1):
                        count = monthly_s[(monthly_s[col_adv_s] == name) & (monthly_s['Month_Idx'] == m)]['Count'].sum()
                        export_s.at[i, f'Month_{m}'] = count

                buffer_s = io.BytesIO()
                with pd.ExcelWriter(buffer_s, engine='xlsxwriter') as writer:
                    export_s.to_excel(writer, index=False, sheet_name='连续送检客户')
                st.download_button("📥 导出“连续送检客户”", buffer_s.getvalue(), "连续送检.xlsx")

            # 导出NP表 (按月)
            if not df_res_n.empty:
                export_n = df_res_n.copy()
                for i, row in export_n.iterrows():
                    name = row['姓名']
                    for m in range(1, x_months + 1):
                        count = monthly_n[(monthly_n[col_adv_n] == name) & (monthly_n['Month_Idx'] == m)]['Count'].sum()
                        export_n.at[i, f'Month_{m}'] = count

                buffer_n = io.BytesIO()
                with pd.ExcelWriter(buffer_n, engine='xlsxwriter') as writer:
                    export_n.to_excel(writer, index=False, sheet_name='连续处方客户')
                st.download_button("📥 导出“连续处方客户”", buffer_n.getvalue(), "连续处方.xlsx")

    except Exception as e:
        st.error(f"处理数据时出错: {e}")
else:
    st.info("👋 请先上传两个数据文件。")
