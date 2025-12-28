import os
import json
import logging
from quart import Quart, jsonify, request, Response, render_template
import aiosqlite
import aiohttp

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

    if not isinstance(scopes, list):
        return jsonify({"error": "Scopes must be a list of strings"}), 400

    # Store as JSON string
    scopes_json = json.dumps(scopes)

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT OR REPLACE INTO services (id, url, scopes) VALUES (?, ?, ?)',
                (service_id, url, scopes_json)
            )
            await db.commit()
        access_url = f"/request/{service_id}"
        return jsonify({"message": "Service registered successfully", "id": service_id, "access_url": access_url}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/unregister/<service_id>', methods=['DELETE'])
async def unregister(service_id):
    if not service_id:
        return jsonify({"error": "Missing required field: id"}), 400
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT 1 FROM services WHERE id = ?', (service_id,)) as cursor:
                if not await cursor.fetchone():
                    return jsonify({"error": "Service not found"}), 404
            
            await db.execute('DELETE FROM services WHERE id = ?', (service_id,))
            await db.commit()
        return jsonify({"message": "Service unregistered successfully", "id": service_id}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get/<service_id>', methods=['GET'])
async def get_service(service_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            async with db.execute('SELECT * FROM services WHERE id = ?', (service_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    scopes = json.loads(row['scopes'])
                        
                    return jsonify({
                        "id": row['id'],
                        "url": row['url'],
                        "scopes": scopes
                    })
                else:
                    return jsonify({"error": "Service not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/list', methods=['GET'])
async def list_services():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT id, url, scopes FROM services') as cursor:
                rows = await cursor.fetchall()
                services = []
                for row in rows:
                    services.append({
                        "id": row['id'],
                        "url": row['url'],
                        "scopes": json.loads(row['scopes'])
                    })
                return jsonify({"services": services}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/request/<path:request_path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
async def proxy_request(request_path):
    # The thing trying to request should also be a registered service with a 'request' scope
    caller_id = request.headers.get('TEST')
    logger.debug(f"Proxy request: path={request_path}, caller_id={caller_id}, method={request.method}")
    
    if not caller_id:
        logger.warning(f"Unauthorized proxy request: missing X-Service-ID header")
        return jsonify({"error": "Unauthorized: Missing X-Service-ID header"}), 401

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Is it registered with the scopes to make requests
        async with db.execute('SELECT scopes FROM services WHERE id = ?', (caller_id,)) as cursor:
            caller_row = await cursor.fetchone()
            if not caller_row:
                logger.warning(f"Caller not found: {caller_id}")
                return jsonify({"error": "Caller not authorized"}), 403
            
            caller_scopes = json.loads(caller_row['scopes'])
       
            if 'request' not in caller_scopes:
                logger.warning(f"Caller {caller_id} missing 'request' scope")
                return jsonify({"error": "Caller does not have 'request' scope"}), 403

        # Match the longest prefix as a service id
        parts = request_path.split('/')
        subpath = ""
        target_row = None

        for i in range(len(parts), 0, -1):
            potential_id = "/".join(parts[:i])
            potential_subpath = "/".join(parts[i:])
            
            async with db.execute('SELECT url, scopes FROM services WHERE id = ?', (potential_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    subpath = potential_subpath
                    target_row = row
                    logger.debug(f"Found service: id={potential_id}, subpath={subpath}")
                    break
        
        if not target_row:
            logger.warning(f"Target service not found for path: {request_path}")
            return jsonify({"error": "Target service not found"}), 404

        # Get target url and scopes
        target_url = target_row['url']
        target_scopes = json.loads(target_row['scopes'])
        
        if 'receive' not in target_scopes:
            logger.warning(f"Target service missing 'receive' scope")
            return jsonify({"error": "Target service does not have 'receive' scope"}), 403

    # Make url
    target_url = target_url.rstrip('/')
    if subpath:
        dest_url = f"{target_url}/{subpath}"
    else:
        dest_url = target_url
    
    logger.info(f"Proxying {request.method} request to: {dest_url}")
    
    method = request.method
    
    # Filter headers to avoid conflicts
    excluded_headers = {'host', 'content-length', 'transfer-encoding', 'connection', 'keep-alive'}
    headers = {key: value for key, value in request.headers.items() if key.lower() not in excluded_headers}
    logger.debug(f"Forwarded headers: {list(headers.keys())}")
    
    # Get data and params
    data = await request.get_data()
    params = request.args

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            logger.debug(f"Making request: {method} {dest_url}")
            async with session.request(method, dest_url, headers=headers, data=data, params=params, ssl=False) as resp:
                content = await resp.read()
                logger.info(f"Upstream response: status={resp.status}, content_length={len(content)}")
                
                # Quart response
                response = Response(content, status=resp.status)
                
                # Copy headers from upstream response
                for key, value in resp.headers.items():
                    if key.lower() not in ('content-encoding', 'content-length', 'transfer-encoding', 'connection'):
                        response.headers[key] = value
                        
                return response
        except aiohttp.ClientError as e:
            logger.error(f"Upstream connection error: {str(e)}", exc_info=True)
            return jsonify({"error": f"Internal upstream error: {str(e)}"}), 502
        except Exception as e:
            logger.error(f"Proxy error: {str(e)}", exc_info=True)
            return jsonify({"error": f"Internal proxy error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run()