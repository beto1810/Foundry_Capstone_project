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




def get_snowflake_connection():
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
    print(f"Creating table: {TABLE_NAME}")
    conn = get_snowflake_connection()
    print(f"Connected to Snowflake: {conn}")
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE_NAME} 
                (ID INT, Full_Name STRING, Gender STRING, DATE_TIME TIMESTAMP_LTZ, 
                Q01 BOOLEAN, Q02 BOOLEAN, Q03 BOOLEAN, Q04 BOOLEAN, 
                Q05 BOOLEAN, Q06 BOOLEAN, Q07 BOOLEAN, Q08 BOOLEAN, 
                Q09 BOOLEAN, Q10 BOOLEAN, Q11 BOOLEAN, Q12 BOOLEAN, Q13 BOOLEAN)""")
    conn.commit()
    cur.close()
    conn.close()

@task()
def load_api():
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

        print(f"Data loaded successfully: {api_df}")
        # Convert DATE_TIME to proper format

        return api_df
    else:
        print(f"Failed to load data: {response.status_code}")
        return None

@task()
def check_latest_date():
    print(f"Checking latest date in Snowflake table: {TABLE_NAME}")
    conn = get_snowflake_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT MAX(DATE_TIME) FROM {TABLE_NAME}")
    result = cur.fetchone()
    latest_date = result[0] if result else None
    "checking latest date in input data"
    

@task()
def filter_new_data(api_df, latest_date):
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
def load_data_to_snowflake(new_data):
    if new_data is None or new_data.empty:
        print("No new data to load into Snowflake.")
        return

    conn = get_snowflake_connection()
    cur = conn.cursor()
    new_data_columns = new_data.columns.tolist()
    print(f"New data columns: {new_data_columns}")
    # Insert new data into Snowflake table
    new_data['Date_Time'] = pd.to_datetime(new_data['Date_Time'], format='%d/%m/%Y %H:%M:%S').dt.strftime('%Y-%m-%d %H:%M:%S')
    for index, row in new_data.iterrows():
        print(row['Date_Time'])

        cur.execute(f"""INSERT INTO {TABLE_NAME} 
                    (ID, FULL_NAME, GENDER, DATE_TIME, Q01, Q02, Q03, Q04, Q05, Q06, Q07, Q08, Q09, Q10, Q11, Q12, Q13)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (row['ID'], row['Full_Name'], row['Gender'], row['Date_Time'],
             row['Q01'], row['Q02'], row['Q03'], row['Q04'],
             row['Q05'], row['Q06'], row['Q07'], row['Q08'],
             row['Q09'], row['Q10'], row['Q11'], row['Q12'], row['Q13'])) 
                    
    conn.commit()
    cur.close()
    conn.close()
    print("Data inserted successfully.")



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