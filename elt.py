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


load_dotenv()
# Load environment variables
# Load environment variables from .env file
api_key  = os.getenv('API_KEY')
sheet_id = os.getenv('SHEET_ID')
tab_range = os.getenv('TAB_RANGE_')

# Define the API endpoint and parameters
end_point = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{tab_range}?key={api_key}"


# Make a GET request to the API
response = requests.get(end_point)
# Check if the request was successful
if response.status_code == 200:
    # Parse the JSON response
    data = response.json()
    # Extract the values from the response
    values = data.get('values', [])
    
    # Convert the values to a DataFrame
    df = pd.DataFrame(values[0:], columns=values[0])
    
    # Print the DataFrame

def get_snowflake_connection():
    # TODO 1: Specify Airflow variables. Import them here.
    return snowflake.connector.connect(
        user=os.getenv('SNOWFLAKE_USER'),
        account=os.getenv('SNOWFLAKE_ACCOUNT'),
        password= os.getenv('SNOWFLAKE_PASSWORD'),
        database= os.getenv('SNOWFLAKE_DATABASE'),
        schema= os.getenv('SNOWFLAKE_SCHEMA'),
    )

def get_snowflake_hook():
    return SnowflakeHook(snowflake_conn_id='snowflake_default')

TABLE_NAME = "test_table"

@task()
def create_table():
    print(f"Creating table: {TABLE_NAME}")
    conn = get_snowflake_connection()
    print(f"Connected to Snowflake: {conn}")
    cur = conn.cursor()
    cur.execute(f"CREATE OR REPLACE TABLE {TABLE_NAME} (id STRING, data INT)")
    conn.commit()
    cur.close()
    conn.close()

@dag(
    dag_id="airflow_lab",
    schedule_interval=None,
    start_date=datetime(2025, 3, 1),
    catchup=False
)
def airflow_lab():
    
    create_table_task = create_table()

    create_table_task 

dag = airflow_lab()