import os
from quart import Quart, jsonify, request, Response
import aiosqlite
import aiohttp

app = Quart(__name__)
DB_PATH = 'Data/service_workers.db'

@app.before_serving
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS services (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                scopes TEXT NOT NULL
            )
        ''')
        await db.commit()

@app.route('/register', methods=['POST'])
async def register():
    data = await request.get_json()
    
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
        
    req_fields = ['id', 'url', 'scopes']
    if not all(field in data for field in req_fields):
        missing_fields = {', '.join(req_fields)}
        return jsonify({"error": f"Missing required fields: {missing_fields}"}), 400
    
    service_id = data['id']
    url = data['url']
    scopes = data['scopes']
    
    # Scopes to string if list
    if isinstance(scopes, list):
        scopes = ",".join(scopes)

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT OR REPLACE INTO services (id, url, scopes) VALUES (?, ?, ?)',
                (service_id, url, scopes)
            )
            await db.commit()
        return jsonify({"message": "Service registered successfully", "id": service_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get/<service_id>', methods=['GET'])
async def get_service(service_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM services WHERE id = ?', (service_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return jsonify({
                    "id": row['id'],
                    "url": row['url'],
                    "scopes": row['scopes']
                })
            else:
                return jsonify({"error": "Service not found"}), 404

@app.route('/request/<service_id>/<path:subpath>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
async def proxy_request(service_id, subpath):
    # The thing trying to request should also be a registered service with a 'request' scope
    caller_id = request.headers.get('X-Service-ID')
    if not caller_id:
        return jsonify({"error": "Unauthorized: Missing X-Service-ID header"}), 401

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Is it registered with the scopes to make requests
        async with db.execute('SELECT scopes FROM services WHERE id = ?', (caller_id,)) as cursor:
            caller_row = await cursor.fetchone()
            if not caller_row:
                return jsonify({"error": "Caller not authorized"}), 403
            
            caller_scopes = caller_row['scopes'].split(',')
            if 'request' not in caller_scopes:
                 return jsonify({"error": "Caller does not have 'request' scope"}), 403

        # Get target url and scopes
        target_url = None
        async with db.execute('SELECT url, scopes FROM services WHERE id = ?', (service_id,)) as cursor:
            target_row = await cursor.fetchone()
            if target_row:
                target_url = target_row['url']
                target_scopes = target_row['scopes'].split(',')
                
                if 'receive' not in target_scopes:
                    return jsonify({"error": "Target service does not have 'receive' scope"}), 403
            else:
                 return jsonify({"error": "Service not found"}), 404

    # Make url
    target_url = target_url.rstrip('/')
    dest_url = f"{target_url}/{subpath}"
    
    method = request.method
    
    # Filter headers to avoid conflicts (e.g. Host) *
    # Todo: figure out what will break later
    headers = {key: value for key, value in request.headers.items() if key.lower() != 'host'}
    
    # Get data and params
    data = await request.get_data()
    params = request.args

    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(method, dest_url, headers=headers, data=data, params=params) as resp:
                content = await resp.read()
                
                # Quart response
                response = Response(content, status=resp.status)
                
                # Copy headers from upstream response
                for key, value in resp.headers.items():
                    if key.lower() not in ('content-encoding', 'content-length', 'transfer-encoding', 'connection'):
                        response.headers[key] = value
                        
                return response
        except aiohttp.ClientError as e:
             return jsonify({"error": f"Intrenal upstream error: {str(e)}"}), 502
        except Exception as e:
            return jsonify({"error": f"Internal proxy error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run()