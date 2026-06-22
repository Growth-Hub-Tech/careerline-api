import pymysql
import os
from dotenv import load_dotenv

#Load environment variables from .env file
load_dotenv()

#Create connection using environment variables
def get_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        connect_timeout=5,
        cursorclass=pymysql.cursors.DictCursor
    )

#Fetch multiple rows
def fetch_all(query, params=None):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()
    finally:
        conn.close()

#fetch single row
def fetch_one(query, params=None):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()
    finally:
        conn.close()

#Execute INSERT / UPDATE
def execute(query, params=None):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            conn.commit()
    finally:
        conn.close()

#Testing connection
if __name__ == "__main__":
    print("Testing DB connection...")
    try:
        conn = get_connection()
        print("Connected successfully!")
        conn.close()
    except Exception as e:
        print("Connection failed:", e)