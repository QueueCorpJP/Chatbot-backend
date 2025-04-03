from psycopg2.extensions import connection as Connection

async def get_uploaded_resources_by_company_id(company_id: str, db: Connection):
    """ユーザーが存在するか確認します"""
    cursor = db.cursor()
    if company_id == None:
        cursor.execute("SELECT id, name, type, uploaded_at, active FROM document_sources ")
    else:
        cursor.execute("SELECT id, name, type, uploaded_at, active FROM document_sources WHERE company_id = %s", (company_id,))
    # return cursor.fetchone() is not 
    sources = cursor.fetchall()
    resources = []
    for source in sources:
        resources.append({
            "id": source["id"],
            "name": source["name"],
            "type": source["type"],
            "timestamp": source["uploaded_at"],
            "active": source["active"]
        })
    
    return {
        "resources": resources,
        "message": f"{len(resources)}件のリソースが見つかりました"
    }

async def toggle_resource_active_by_id(resource_id: str, db: Connection):
    cursor = db.cursor()
    cursor.execute("SELECT name, active FROM document_sources WHERE id = %s", (resource_id,))
    result = cursor.fetchone()
    if result is None:
        return False  
    current_active_state = result["active"]
    resource_name = result["name"]
    new_active_state = not current_active_state
    cursor.execute("UPDATE document_sources SET active = %s WHERE id = %s", (new_active_state, resource_id))
    db.commit()
   
    return {
        "name": resource_name,
        "active": new_active_state,
        "message": f"リソース '{resource_name}' のアクティブ状態を {new_active_state} に変更しました"
    }

async def remove_resource_by_id(resource_id: str, db: Connection):
    cursor = db.cursor()
    cursor.execute("DELETE FROM document_sources WHERE id = %s", (resource_id,))
    db.commit()
   
    return {
        "name": "",
        "message": f"リソースを削除しました"
    }

