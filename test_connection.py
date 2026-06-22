import pymysql

try:
    conn = pymysql.connect(
        host="172.26.160.1",
        port=3306,
        user="root",
        password="#iamExcel191878",
        database="tech_skill_assessment"
    )

    cursor = conn.cursor()
    cursor.execute("SHOW TABLES;")
    tables = cursor.fetchall()

    print("CONNECTED SUCCESSFULLY")
    print("TABLES:", tables)

    conn.close()

except Exception as e:
    print("CONNECTION FAILED:", e)