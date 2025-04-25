import pandas as pd
import requests 
import json
from datetime import datetime
import os 
from dotenv import load_dotenv

import snowflake.connector
from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook
from airflow.sensors.base import PokeReturnValue
from airflow.hooks.base import BaseHook


#Local folder for parquette files
LOCAL_DIR = "/tmp/data"  # Local directory for Parquet files
STAGE_NAME = "my_internal_stage"  # Snowflake internal stage

def get_snowflake_connection():
    # TODO 1: Specify Airflow variables. Import them here.
    conn = BaseHook.get_connection("snowflake_default")
    return snowflake.connector.connect(
        user=conn.login,
        account= conn.extra_dejson.get("account"),
        password= conn.password,
        database= conn.extra_dejson.get("database"),
        schema= conn.schema
    )

def get_snowflake_hook():

    return SnowflakeHook(snowflake_conn_id='snowflake_default')

TABLE_NAME = "TB_SYMPTOMS_GGSHEET"


@task()
def create_table():
    ## Create Snowflake table if it doesn't exist
    print(f"Creating table: {TABLE_NAME}")
    conn = get_snowflake_connection()
    print(f"Connected to Snowflake: {conn}")
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE_NAME} 
                (ID INT, FULL_NAME STRING, GENDER STRING, DATE_TIME TIMESTAMP_LTZ, 
                Q01 BOOLEAN, Q02 BOOLEAN, Q03 BOOLEAN, Q04 BOOLEAN, 
                Q05 BOOLEAN, Q06 BOOLEAN, Q07 BOOLEAN, Q08 BOOLEAN, 
                Q09 BOOLEAN, Q10 BOOLEAN, Q11 BOOLEAN, Q12 BOOLEAN, Q13 BOOLEAN)""")
    conn.commit()
    cur.close()
    conn.close()

@task()
def load_api():
    ## Load data from Google Sheets API
    print("Loading data from Google Sheets API")
    sheet_id = Variable.get("SHEET_ID")
    tab_range = Variable.get("TAB_RANGE")
    api_key = Variable.get("API_KEY")
    end_point = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{tab_range}?key={api_key}"
    print(end_point)
    response = requests.get(end_point)
    if response.status_code == 200:
        data = response.json()
        values = data.get('values', [])
        api_df = pd.DataFrame(values[1:], columns=values[0])

        # Convert DATE_TIME to proper format

        api_df['DATE_TIME'] = pd.to_datetime(api_df['DATE_TIME'], format='%d/%m/%Y %H:%M:%S')
        api_df['DATE_TIME'] = api_df['DATE_TIME'].dt.tz_localize('UTC')
        api_df['DATE_TIME'] = api_df['DATE_TIME'].dt.strftime('%Y-%m-%d %H:%M:%S')
        print(f"Data loaded successfully: {api_df}")

        return api_df
    else:
        print(f"Failed to load data: {response.status_code}")
        return None

@task()
def check_latest_date():
    ## Check the latest date in Snowflake table
    print(f"Checking latest date in Snowflake table: {TABLE_NAME}")
    conn = get_snowflake_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT MAX(DATE_TIME) FROM {TABLE_NAME}")
    result = cur.fetchone()
    latest_date = result[0] if result else None
    "checking latest date in input data"
    print(f"Latest date in Snowflake table: {latest_date}")
    cur.close()
    conn.close()
    return latest_date

    

@task()
def filter_new_data(api_df, latest_date):
    ## Filter new data based on the latest date
    if api_df is None or api_df.empty:
        print("No API data to filter.")
        return None

    if latest_date is None:
        print("No latest date found. Returning all API data.")
        return api_df

    # Filter only new data
    new_data = api_df[api_df['Date_Time'] > latest_date]
    print(f"New rows to insert: {new_data.shape[0]}")
    return new_data if not new_data.empty else None
    
@task()
def load_data_to_snowflake(new_data, **context):
    ## Load new data into Snowflake table
    ### Saved filtered input data to parquet file in local storage - can replace with S3 or GCS
        
    if new_data is None or new_data.empty:
        print("No new data to load into Snowflake")
        return

    # Local file path for Parquet
    os.makedirs(LOCAL_DIR, exist_ok=True)
    parquet_file = f"{LOCAL_DIR}/data_{context['ds_nodash']}.parquet"
    stage_path = f"@{STAGE_NAME}/data_{context['ds_nodash']}.parquet"

    try:
        # Validate schema
        expected_columns = [
            "ID", "FULL_NAME", "GENDER", "DATE_TIME",
            "Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08", "Q09", "Q10", "Q11", "Q12", "Q13"
        ]
        if list(new_data.columns) != expected_columns:
            raise ValueError(f"DataFrame columns {list(new_data.columns)} do not match expected {expected_columns}")

        # Convert boolean columns and ensure data types
        new_data['ID'] = new_data['ID'].astype(int)
        for col in ["Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08", "Q09", "Q10", "Q11", "Q12", "Q13"]:
            new_data[col] = new_data[col].astype(bool)
        new_data['FULL_NAME'] = new_data['FULL_NAME'].astype(str)
        new_data['GENDER'] = new_data['GENDER'].astype(str)

        # Save to local storage as Parquet
        new_data.to_parquet(parquet_file, compression="snappy", index=False)
        print(f"Saved Parquet file to local storage: {parquet_file}")

        # Upload to Snowflake internal stage
        conn = get_snowflake_connection()
        cur = conn.cursor()
        try:
            if not os.path.exists(parquet_file):
                raise FileNotFoundError(f"Parquet file {parquet_file} not found")
            cur.execute(f"PUT file://{parquet_file} {stage_path} AUTO_COMPRESS = FALSE")
            print(f"Uploaded Parquet file to Snowflake stage: {stage_path}")

            # Load into Snowflake table
            cur.execute(f"""
            COPY INTO {TABLE_NAME}
            FROM {stage_path}
            FILE_FORMAT = (TYPE = PARQUET)
            MATCH_BY_COLUMN_NAME = CASE_SENSITIVE
            """)
            conn.commit()
            print(f"Loaded {new_data.shape[0]} rows into {TABLE_NAME}")

            # Clean up staged file
            cur.execute(f"REMOVE {stage_path}")
            print(f"Removed staged file: {stage_path}")
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"Error loading data to Snowflake: {str(e)}")
        raise
    finally:
        # Clean up local file
        if os.path.exists(parquet_file):
            os.remove(parquet_file)
            print(f"Deleted local Parquet file: {parquet_file}")



@dag(
    dag_id="airflow_lab",
    schedule_interval=None,
    start_date=datetime(2025, 3, 1),
    catchup=False
)
def airflow_lab():
    
    create_table_task = create_table()

    load_api_task = load_api()
    check_latest_date_task = check_latest_date()
    filter_new_data_task = filter_new_data(load_api_task, check_latest_date_task)
    load_data_to_snowflake_task = load_data_to_snowflake(filter_new_data_task)
    create_table_task >> load_api_task >> check_latest_date_task >> filter_new_data_task >> load_data_to_snowflake_task 

dag = airflow_lab()