import streamlit as st
import pandas as pd
import nfl_data_py as nfl
from datetime import datetime
from functools import reduce
import plotly.express as px
import pytz # Import the new timezone library

# --- Configuration ---
st.set_page_config(page_title="NFL Stats Explorer", layout="wide")

# --- Data Loading and Caching ---
@st.cache_data(ttl=60 * 60 * 12)
def load_weekly_and_ngs_data(year):
    """Loads and caches the standard weekly and NGS data for offensive stats."""
    weekly_df = nfl.import_weekly_data(years=[year])
    ngs_data = {}
    for stat_type in ['passing', 'rushing', 'receiving']:
        ngs_data[stat_type] = nfl.import_ngs_data(stat_type=stat_type, years=[year])
    return weekly_df, ngs_data

@st.cache_data(ttl=60 * 60 * 12)
def load_and_aggregate_pbp_data(year):
    """
    Loads and caches Play-by-Play data for a given year and aggregates it
    to create a clean, accurate defensive stats dataframe.
    """
    # More robust PBP data loading
    pbp_df = nfl.import_pbp_data(years=[year], downcast=True, cache=False)
    rosters_df = nfl.import_seasonal_rosters(years=[year])
    
    def_stats_dict = {
        'sacks': ('sack', 'sack_player_name'),
        'interceptions': ('interception', 'interception_player_name'),
        'fumbles_forced': ('fumble_forced', 'forced_fumble_player_1_player_name'),
        'passes_defended': ('pass_defense_1_player_name', 'pass_defense_1_player_name'),
        'fumbles_recovered': ('fumble', 'fumble_recovery_1_player_name')
    }

    aggregated_stats = []
    for stat_name, (flag_col, player_col) in def_stats_dict.items():
        if player_col in pbp_df.columns:
            df_filtered = pbp_df.dropna(subset=[player_col])
            
            if stat_name in ['passes_defended', 'fumbles_recovered']:
                stat_df = df_filtered.groupby(player_col).size().reset_index(name=stat_name)
            else:
                stat_df = df_filtered[df_filtered[flag_col] == 1].groupby(player_col)[flag_col].sum().reset_index()
            
            stat_df = stat_df.rename(columns={flag_col: stat_name, player_col: 'player_display_name'})
            aggregated_stats.append(stat_df)

    if not aggregated_stats: return pd.DataFrame()

    defensive_df = reduce(lambda left, right: pd.merge(left, right, on='player_display_name', how='outer'), aggregated_stats)
    defensive_df = defensive_df.fillna(0)

    stat_cols_to_convert = [stat for stat in def_stats_dict.keys() if stat in defensive_df.columns]
    defensive_df[stat_cols_to_convert] = defensive_df[stat_cols_to_convert].astype(int)

    player_positions = rosters_df[['player_name', 'position']].rename(columns={'player_name': 'player_display_name'})
    player_positions = player_positions.drop_duplicates(subset=['player_display_name'])
    
    final_def_df = pd.merge(defensive_df, player_positions, on='player_display_name', how='left')
    return final_def_df

# --- Stat Dictionaries ---
OFFENSE_STATS = {
    'Passing Yards': 'passing_yards', 'Passing TDs': 'passing_tds', 'Interceptions Thrown': 'interceptions', 
    'Sacks Taken': 'sacks', 'Rushing Yards': 'rushing_yards', 'Rushing TDs': 'rushing_tds',
    'Receptions': 'receptions', 'Receiving Yards': 'receiving_yards', 'Receiving TDs': 'receiving_tds'
}
DEFENSE_STATS = {
    'Sacks': 'sacks', 'Interceptions': 'interceptions', 'Passes Defended': 'passes_defended',
    'Forced Fumbles': 'fumbles_forced', 'Fumbles Recovered': 'fumbles_recovered'
}
NGS_TRANSLATIONS = {
    'avg_time_to_throw': 'Avg Time to Throw (sec)', 'avg_completed_air_yards': 'Avg Completed Air Yards',
    'avg_intended_air_yards': 'Avg Intended Air Yards', 'efficiency': 'Rushing Efficiency',
    'rush_yards_over_expected': 'Rush Yards Over Expected'
}

COLUMN_RENAME_MAP = {
    'player_display_name': 'Player', 'position': 'Pos', 'week': 'Week',
    **{v: k for k, v in OFFENSE_STATS.items()},
    **{v: k for k, v in DEFENSE_STATS.items()}
}

# --- UI and Logic ---
st.title("🏈 NFL Stats Explorer")

# --- Timezone Corrected Refresh Button ---
def get_eastern_time():
    utc_now = datetime.now(pytz.utc)
    eastern = pytz.timezone('US/Eastern')
    return utc_now.astimezone(eastern).strftime("%B %d, %Y at %I:%M %p %Z")

if 'last_refresh' not in st.session_state:
    st.session_state['last_refresh'] = get_eastern_time()

col1, col2 = st.columns([3, 1])
with col1:
    st.write(f"**Data last refreshed:** {st.session_state.get('last_refresh', 'N/A')}")
with col2:
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.session_state['last_refresh'] = get_eastern_time()
        st.rerun()

st.sidebar.header("Filters")
selected_year = st.sidebar.selectbox("Select Season", [2025, 2024, 2023, 2022], index=1)
season_type_toggle = st.sidebar.radio("Select Season Type", ('All', 'Regular Season', 'Postseason'))

weekly_df_raw, ngs_data_raw = load_weekly_and_ngs_data(selected_year)
defensive_df_raw = load_and_aggregate_pbp_data(selected_year)

if season_type_toggle == 'Regular Season':
    weekly_df = weekly_df_raw[weekly_df_raw['season_type'] == 'REG'].copy()
elif season_type_toggle == 'Postseason':
    weekly_df = weekly_df_raw[weekly_df_raw['season_type'] == 'POST'].copy()
else:
    weekly_df = weekly_df_raw.copy()

defensive_df = defensive_df_raw

if weekly_df.empty:
    st.warning(f"No offensive data available for {selected_year} {season_type_toggle}.")
    st.stop()

all_players = sorted(weekly_df['player_display_name'].unique())
tab1, tab2 = st.tabs(["🏆 Top Performers", "🔍 Player Search"])

# (The rest of the app logic remains the same)
with tab1:
    st.header(f"Top Performers - {selected_year} Season")
    main_category = st.selectbox("Select Stat Category", ["Offense", "Defense", "Next Gen Stats"])

    chart_df = None
    chart_stat_col = None
    chart_title = ""

    if main_category == "Defense":
        st.info("Defensive stats are aggregated from season-long Play-by-Play data and include both regular and post-season.")
        sub_category_key = st.selectbox("Select Defense Stat", list(DEFENSE_STATS.keys()))
        stat_column = DEFENSE_STATS[sub_category_key]
        
        if stat_column in defensive_df.columns:
            leaderboard = defensive_df.sort_values(by=stat_column, ascending=False)
            leaderboard = leaderboard[leaderboard[stat_column] > 0].head(20)
            display_cols = ['player_display_name', 'position', stat_column]
            leaderboard = leaderboard[display_cols].reset_index(drop=True)
            leaderboard.index = leaderboard.index + 1
            st.dataframe(leaderboard.rename(columns=COLUMN_RENAME_MAP))
            chart_df = leaderboard
            chart_stat_col = stat_column
            chart_title = f"Top 20 Leaders: {sub_category_key}"
            
    else:
        st.header(f"Top Performers - {selected_year} {season_type_toggle}")
        min_week, max_week = int(weekly_df['week'].min()), int(weekly_df['week'].max())
        week_range = st.slider("Select Week Range", min_week, max_week, (min_week, max_week), key="main_slider")
        df_for_leaders = weekly_df[(weekly_df['week'] >= week_range[0]) & (weekly_df['week'] <= week_range[1])]
        
        if main_category == "Offense":
            sub_category_key = st.selectbox("Select Offense Stat", list(OFFENSE_STATS.keys()))
            stat_column = OFFENSE_STATS[sub_category_key]
            display_cols = ['player_display_name', 'position', stat_column]
            groupby_cols = ['player_display_name', 'position']
        
        else:
            ngs_type = st.selectbox("Select NGS Category", ["Passing", "Rushing", "Receiving"])
            df_for_leaders = ngs_data_raw[ngs_type.lower()]
            df_for_leaders = df_for_leaders[df_for_leaders['season'] == selected_year]
            ngs_stat_cols = {NGS_TRANSLATIONS.get(col, col): col for col in df_for_leaders.columns if col in NGS_TRANSLATIONS}
            sub_category_key = st.selectbox("Select Next Gen Stat", list(ngs_stat_cols.keys()))
            stat_column = ngs_stat_cols[sub_category_key]
            display_cols = ['player_display_name', stat_column]
            groupby_cols = ['player_display_name']

        if stat_column in df_for_leaders.columns and not df_for_leaders.empty:
            aggregation = {'sum' if 'avg' not in stat_column else 'mean'}
            leaderboard = df_for_leaders.groupby(groupby_cols)[stat_column].sum().reset_index()
            leaderboard = leaderboard.sort_values(by=stat_column, ascending=False).head(20).reset_index(drop=True)
            leaderboard.index = leaderboard.index + 1
            st.dataframe(leaderboard[display_cols].rename(columns=COLUMN_RENAME_MAP))
            chart_df = leaderboard
            chart_stat_col = stat_column
            chart_title = f"Top 20 Leaders: {sub_category_key} (Weeks {week_range[0]}-{week_range[1]})"

    if chart_df is not None and chart_stat_col:
        st.write("---")
        st.write("**Leaderboard Chart**")
        fig = px.bar(
            chart_df,
            x='player_display_name',
            y=chart_stat_col,
            title=chart_title,
            labels={'player_display_name': 'Player', chart_stat_col: chart_title.split(':')[-1].strip()}
        )
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.header("Search for Player Stats (Offense)")
    player_name = st.selectbox("Select a Player", all_players)

    if player_name:
        st.subheader(f"Stats for {player_name} - {selected_year} {season_type_toggle}")
        player_weekly_stats = weekly_df[weekly_df['player_display_name'] == player_name].copy()
        
        cols_with_data = [
            col for col in OFFENSE_STATS.values() 
            if col in player_weekly_stats.columns and player_weekly_stats[col].sum() > 0
        ]
        
        st.write("**Full Season Aggregate Stats**")
        if cols_with_data:
            agg_stats = player_weekly_stats[cols_with_data].sum().astype(int)
            agg_stats_df = agg_stats.rename(COLUMN_RENAME_MAP).reset_index()
            agg_stats_df.columns = ['Statistic', 'Value']
            st.table(agg_stats_df)
        else:
            st.info("This player has no recorded stats for the selected season/type.")

        if cols_with_data:
            st.write("---")
            st.write("**Filter Stats by Week Range**")
            player_min_week, player_max_week = int(player_weekly_stats['week'].min()), int(player_weekly_stats['week'].max())
            player_week_range = st.slider("Select a range of weeks:", player_min_week, player_max_week, (player_min_week, player_max_week), key="player_week_slider")
            player_filtered_df = player_weekly_stats[(player_weekly_stats['week'] >= player_week_range[0]) & (player_weekly_stats['week'] <= player_week_range[1])]
            
            range_agg_stats = player_filtered_df[cols_with_data].sum()
            range_agg_stats = range_agg_stats[range_agg_stats > 0].astype(int)
            
            st.write(f"**Aggregate Stats for Weeks {player_week_range[0]}-{player_week_range[1]}**")
            if not range_agg_stats.empty:
                range_agg_stats_df = range_agg_stats.rename(COLUMN_RENAME_MAP).reset_index()
                range_agg_stats_df.columns = ['Statistic', 'Value']
                st.table(range_agg_stats_df)
            else:
                st.info("No stats recorded in this week range.")
            
            st.write("---")
            
            st.write("**Per-Game Stats**")
            per_game_cols_to_show = ['week'] + cols_with_data
            st.dataframe(player_weekly_stats[per_game_cols_to_show].set_index('week').rename(columns=COLUMN_RENAME_MAP))
            
            st.write("**Performance Chart**")
            chart_options = {k: v for k, v in OFFENSE_STATS.items() if v in cols_with_data}
            chart_stat_key = st.selectbox("Select Stat to Visualize", list(chart_options.keys()))
            chart_stat_col = chart_options.get(chart_stat_key)

            if chart_stat_col:
                fig = px.line(player_weekly_stats, x='week', y=chart_stat_col, title=f"Weekly {chart_stat_key}", markers=True)
                st.plotly_chart(fig, use_container_width=True)
